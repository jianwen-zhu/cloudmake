from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import math
import os
import random
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.fspath(Path(__file__).resolve().parents[2] / "core"))
from run_state import update


EX_TEMPFAIL = 75
CAPACITY_MARKER = "TooManyAssignmentsError"
PENDING_SCHEMA = 1


@dataclass(frozen=True)
class ClientResult:
    returncode: int
    stdout: str
    timed_out: bool = False


def atomic_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def write_receipt(
    path: Path,
    *,
    session: str,
    attempts: int,
    outcome: str,
    classification: str | None = None,
    retry_after_seconds: int | None = None,
) -> None:
    payload: dict[str, object] = {
        "schema": 1,
        "provider": "colab",
        "session": session,
        "attempts": attempts,
        "outcome": outcome,
    }
    if classification is not None:
        payload["classification"] = classification
    if retry_after_seconds is not None:
        payload["retry_after_seconds"] = retry_after_seconds
    atomic_json(path, payload)


def load_pending(path: Path, session: str) -> dict[str, object] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return {"invalid": True}
    if (
        not isinstance(payload, dict)
        or payload.get("schema") != PENDING_SCHEMA
        or payload.get("provider") != "colab"
        or payload.get("session") != session
    ):
        return {"invalid": True}
    numeric_fields = (
        "first_submitted_at",
        "last_submitted_at",
        "replacement_allowed_at",
        "allocation_requests",
        "reconcile_runs",
        "empty_observations",
    )
    if any(
        isinstance(payload.get(field), bool)
        or not isinstance(payload.get(field), (int, float))
        or payload[field] < 0
        for field in numeric_fields
    ):
        return {"invalid": True}
    return payload


def new_pending(arguments: argparse.Namespace, *, origin: str) -> dict[str, object]:
    now = time.time()
    return {
        "schema": PENDING_SCHEMA,
        "provider": "colab",
        "session": arguments.session,
        "gpu": arguments.gpu,
        "origin": origin,
        "first_submitted_at": now,
        "last_submitted_at": now,
        "replacement_allowed_at": now + arguments.replace_after_seconds,
        "allocation_requests": 1 if origin == "submission-timeout" else 0,
        "reconcile_runs": 0,
        "empty_observations": 0,
    }


def save_pending(arguments: argparse.Namespace, pending: dict[str, object]) -> None:
    atomic_json(arguments.pending_state, pending)


def clear_pending(arguments: argparse.Namespace) -> None:
    arguments.pending_state.unlink(missing_ok=True)


def record_operation_failure(state_file: Path, receipt_file: Path) -> None:
    try:
        receipt = json.loads(receipt_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        receipt = {}
    outcome = receipt.get("outcome")
    provider_state, runtime_state, failure_code = {
        "capacity-timeout": (
            "absent",
            "absent",
            "capacity_retry_deadline_exceeded",
        ),
        "capacity-unavailable": ("absent", "absent", "capacity_unavailable"),
        "session-query-failed": (
            "unknown",
            "unreachable",
            "session_listing_failed",
        ),
        "allocation-failed": ("unknown", "unreachable", "allocation_failed"),
        "allocation-ambiguous": (
            "unknown",
            "unreachable",
            "allocation_ambiguous",
        ),
        "allocation-deferred": (
            "unknown",
            "unreachable",
            "allocation_reconciliation_deferred",
        ),
        "retry-configuration-failed": (
            "absent",
            "absent",
            "retry_configuration_failed",
        ),
        "interrupted": ("unknown", "unreachable", "allocation_interrupted"),
    }.get(
        outcome,
        ("unknown", "unreachable", "allocation_receipt_missing"),
    )
    update(
        state_file,
        {
            "phase": "allocation",
            "provider_state": provider_state,
            "runtime_state": runtime_state,
            "session_created": False,
            "target_submission": "not_submitted",
            "retry_safe": outcome not in {"allocation-ambiguous", "interrupted"},
            "failure_code": failure_code,
        },
    )


def run(command: list[str], timeout: float) -> ClientResult:
    try:
        completed = subprocess.run(
            command,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=max(0.01, timeout),
        )
    except subprocess.TimeoutExpired as error:
        output = error.stdout or ""
        if isinstance(output, bytes):
            output = output.decode(errors="replace")
        return ClientResult(124, output, timed_out=True)
    return ClientResult(completed.returncode, completed.stdout)


def emit(output: str) -> None:
    if output:
        print(output, end="" if output.endswith("\n") else "\n")


def exit_status(returncode: int) -> int:
    return returncode if 1 <= returncode <= 255 else 1


def session_is_listed(output: str, session: str) -> bool:
    prefix = f"[{session}]"
    return any(
        line == prefix or line.startswith(prefix + " ")
        for line in output.splitlines()
    )


def unknown_session_is_listed(output: str) -> bool:
    return any(
        line == "[?]" or line.startswith("[?] ")
        for line in output.splitlines()
    )


def command_timeout(arguments: argparse.Namespace, deadline: float | None = None) -> float:
    if deadline is None:
        return arguments.command_timeout
    return min(arguments.command_timeout, max(0.01, deadline - time.monotonic()))


def inspect_sessions(
    arguments: argparse.Namespace, *, deadline: float | None = None
) -> tuple[str, ClientResult]:
    result = run(
        [arguments.client, "sessions"],
        command_timeout(arguments, deadline),
    )
    if result.returncode != 0:
        return "error", result
    if session_is_listed(result.stdout, arguments.session):
        return "named", result
    if unknown_session_is_listed(result.stdout):
        return "unknown", result
    return "absent", result


def reconcile_sessions(
    arguments: argparse.Namespace,
    *,
    deadline: float | None = None,
    checks: int = 3,
) -> tuple[str, ClientResult]:
    last = ClientResult(1, "")
    for check in range(checks):
        if deadline is not None and check > 0 and time.monotonic() >= deadline:
            return "absent", last
        state, last = inspect_sessions(arguments, deadline=deadline)
        if (
            state == "error"
            and last.timed_out
            and deadline is not None
            and time.monotonic() >= deadline
        ):
            return "absent", last
        if state != "absent" or check + 1 == checks:
            return state, last
        remaining = math.inf if deadline is None else deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(arguments.recheck_seconds, remaining))
    return "absent", last


def recovery_command(arguments: argparse.Namespace) -> str:
    options = [
        f"COLAB_SESSION={arguments.session}",
        "cloudmake",
        "-b",
        "colab",
    ]
    if arguments.gpu:
        options.append(f"--gpu={arguments.gpu}")
    options.extend(
        [f"--retry-for={duration(arguments.recovery_retry_seconds)}", "--start"]
    )
    return " ".join(options)


def allocation_deferred(
    arguments: argparse.Namespace,
    attempts: int,
    message: str,
    pending: dict[str, object],
    *,
    classification: str,
) -> int:
    save_pending(arguments, pending)
    until_replacement = max(
        0.0, float(pending["replacement_allowed_at"]) - time.time()
    )
    retry_after = max(
        1,
        math.ceil(
            until_replacement
            if until_replacement > 0
            else arguments.recovery_retry_seconds
        ),
    )
    print(f"[cloudmake] {message}", file=sys.stderr)
    print(
        "[cloudmake] project target was not submitted. Try later: wait at least "
        f"{duration(retry_after, round_up=True)}, then run:",
        file=sys.stderr,
    )
    print(f"[cloudmake]   {recovery_command(arguments)}", file=sys.stderr)
    print(
        "[cloudmake] after --start confirms a ready session, rerun the original "
        "project target explicitly; Cloudmake will not replay it.",
        file=sys.stderr,
    )
    print(
        "[cloudmake] the next invocation will reconcile the saved allocation first; "
        "it may adopt a late named session. Only after the grace period and repeated "
        "empty listings may it issue one bounded replacement for that recovery "
        "window. Further replacements are cooldown-limited. Because "
        "Colab provides no allocation idempotency key, that replacement has a "
        "disclosed duplicate-runtime risk; unnamed sessions are never stopped.",
        file=sys.stderr,
    )
    write_receipt(
        arguments.result,
        session=arguments.session,
        attempts=attempts,
        outcome="allocation-deferred",
        classification=classification,
        retry_after_seconds=retry_after,
    )
    return EX_TEMPFAIL


def tuning(name: str, default: float, *, minimum: float = 0.0) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError as error:
        raise ValueError(f"{name} must be a number") from error
    if not math.isfinite(value) or value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return value


def duration(value: float, *, round_up: bool = False) -> str:
    if value < 1:
        return f"{value:.2f}s"
    seconds = math.ceil(value) if round_up else math.floor(value)
    if seconds < 60:
        return f"{seconds}s"
    if seconds % 3600 == 0:
        return f"{seconds // 3600}h"
    if seconds % 60 == 0:
        return f"{seconds // 60}m"
    minutes, remainder = divmod(seconds, 60)
    return f"{minutes}m{remainder}s"


def pending_replacement_ready(
    arguments: argparse.Namespace, pending: dict[str, object]
) -> bool:
    return (
        time.time() >= float(pending["replacement_allowed_at"])
        and int(pending["reconcile_runs"]) >= 2
        and int(pending["empty_observations"])
        >= arguments.minimum_empty_observations
    )


def poll_pending(
    arguments: argparse.Namespace,
    pending: dict[str, object],
    *,
    deadline: float,
) -> tuple[str, ClientResult]:
    pending["reconcile_runs"] = int(pending["reconcile_runs"]) + 1
    save_pending(arguments, pending)
    last_state = "absent"
    last_result = ClientResult(0, "")
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return last_state, last_result
        state, result = inspect_sessions(arguments, deadline=deadline)
        last_state, last_result = state, result
        emit(result.stdout)
        if state == "named":
            return state, result
        if state == "absent":
            pending["empty_observations"] = int(pending["empty_observations"]) + 1
            save_pending(arguments, pending)
            if pending_replacement_ready(arguments, pending):
                return "replacement-ready", result
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return state, result
        time.sleep(min(arguments.recheck_seconds, remaining))


def reconcile_window(arguments: argparse.Namespace, *, resumed: bool) -> float:
    if arguments.retry_seconds:
        return float(arguments.retry_seconds)
    return (
        arguments.resume_reconcile_seconds
        if resumed
        else arguments.reconcile_seconds
    )


def capacity_timeout(
    arguments: argparse.Namespace, attempts: int, started: float
) -> int:
    elapsed = time.monotonic() - started
    print(
        "[cloudmake] capacity unavailable: colab "
        f"{CAPACITY_MARKER}; attempts={attempts}; "
        f"elapsed={duration(elapsed)} remaining=0s; retry deadline expired",
        file=sys.stderr,
    )
    write_receipt(
        arguments.result,
        session=arguments.session,
        attempts=attempts,
        outcome="capacity-timeout",
        classification=CAPACITY_MARKER,
    )
    return EX_TEMPFAIL


def allocate(arguments: argparse.Namespace) -> int:
    attempts = 0
    arguments.allocation_attempts = attempts
    started = time.monotonic()
    deadline = started + arguments.retry_seconds
    maximum = min(
        60.0, tuning("CLOUDMAKE_RETRY_MAX_SECONDS", 60.0, minimum=0.01)
    )
    base = min(
        maximum, tuning("CLOUDMAKE_RETRY_BASE_SECONDS", 5.0, minimum=0.01)
    )
    jitter = tuning("CLOUDMAKE_RETRY_JITTER", 0.2)
    if jitter > 0.5:
        raise ValueError("CLOUDMAKE_RETRY_JITTER must be between 0 and 0.5")

    pending = load_pending(arguments.pending_state, arguments.session)
    replacement = False
    if pending is not None:
        if pending.get("invalid"):
            print(
                "[cloudmake] saved Colab allocation recovery state is invalid; "
                f"refusing allocation: {arguments.pending_state}",
                file=sys.stderr,
            )
            write_receipt(
                arguments.result,
                session=arguments.session,
                attempts=0,
                outcome="retry-configuration-failed",
                classification="pending-state-invalid",
            )
            return 2
        saved_gpu = pending.get("gpu")
        if isinstance(saved_gpu, str) and saved_gpu != arguments.gpu:
            print(
                "[cloudmake] resuming the unresolved allocation with its original "
                f"accelerator selection: {saved_gpu or 'CPU'}",
                file=sys.stderr,
            )
            arguments.gpu = saved_gpu
        attempts = int(pending["allocation_requests"])
        arguments.allocation_attempts = attempts
        recovery_deadline = time.monotonic() + reconcile_window(
            arguments, resumed=True
        )
        session_state, sessions = poll_pending(
            arguments, pending, deadline=recovery_deadline
        )
        if session_state == "named":
            clear_pending(arguments)
            arguments.resource_state.write_text("reused\n", encoding="utf-8")
            write_receipt(
                arguments.result,
                session=arguments.session,
                attempts=attempts,
                outcome="recovered-late-session",
            )
            return 0
        if session_state == "replacement-ready":
            replacement = True
            print(
                "[cloudmake] the saved allocation remained absent through the grace "
                "period and repeated successful listings; issuing the one allowed "
                "replacement for this recovery window. A late earlier allocation could still "
                "produce a duplicate runtime.",
                file=sys.stderr,
            )
        else:
            classification = {
                "error": "session-discovery-error",
                "unknown": "unnamed-session-visible",
            }.get(session_state, "session-still-unconfirmed")
            return allocation_deferred(
                arguments,
                attempts,
                "Colab still has not confirmed the saved allocation.",
                pending,
                classification=classification,
            )
    else:
        session_state, sessions = reconcile_sessions(
            arguments,
            checks=3 if arguments.prior_selection else 1,
        )
        if session_state == "error":
            emit(sessions.stdout)
            write_receipt(
                arguments.result,
                session=arguments.session,
                attempts=attempts,
                outcome="session-query-failed",
            )
            return exit_status(sessions.returncode)
        if session_state == "unknown":
            emit(sessions.stdout)
            pending = new_pending(arguments, origin="unnamed-session-visible")
            return allocation_deferred(
                arguments,
                attempts,
                "Colab reported an unnamed session that may be the selected runtime.",
                pending,
                classification="unnamed-session-visible",
            )
        if session_state == "named":
            clear_pending(arguments)
            arguments.resource_state.write_text("reused\n", encoding="utf-8")
            write_receipt(
                arguments.result,
                session=arguments.session,
                attempts=attempts,
                outcome="reused",
            )
            return 0

    command = [arguments.client, "new", "-s", arguments.session]
    if arguments.gpu:
        command.extend(["--gpu", arguments.gpu])

    while True:
        if not replacement and attempts and time.monotonic() >= deadline:
            return capacity_timeout(arguments, attempts, started)
        attempts += 1
        arguments.allocation_attempts = attempts
        if replacement:
            assert pending is not None
            pending["allocation_requests"] = attempts
            pending["last_submitted_at"] = time.time()
            pending["replacement_allowed_at"] = (
                time.time() + arguments.replacement_cooldown_seconds
            )
            pending["reconcile_runs"] = 0
            pending["empty_observations"] = 0
            save_pending(arguments, pending)
        request_deadline = (
            deadline if arguments.retry_seconds and not replacement else None
        )
        try:
            result = run(command, command_timeout(arguments, request_deadline))
        except KeyboardInterrupt:
            if pending is None:
                pending = new_pending(arguments, origin="submission-interrupted")
            pending["allocation_requests"] = attempts
            pending["last_submitted_at"] = time.time()
            save_pending(arguments, pending)
            raise
        if result.returncode == 0:
            emit(result.stdout)
            clear_pending(arguments)
            arguments.resource_state.write_text("started\n", encoding="utf-8")
            write_receipt(
                arguments.result,
                session=arguments.session,
                attempts=attempts,
                outcome="allocated-replacement" if replacement else "allocated",
            )
            return 0

        if result.timed_out:
            emit(result.stdout)
            if pending is None:
                pending = new_pending(arguments, origin="submission-timeout")
            else:
                pending["allocation_requests"] = attempts
                pending["last_submitted_at"] = time.time()
            save_pending(arguments, pending)
            recovery_window = (
                max(0.01, deadline - time.monotonic())
                if arguments.retry_seconds
                else arguments.reconcile_seconds
            )
            recovery_deadline = time.monotonic() + recovery_window
            session_state, sessions = poll_pending(
                arguments, pending, deadline=recovery_deadline
            )
            if session_state == "named":
                clear_pending(arguments)
                arguments.resource_state.write_text(
                    "reused\n" if replacement else "started\n", encoding="utf-8"
                )
                write_receipt(
                    arguments.result,
                    session=arguments.session,
                    attempts=attempts,
                    outcome="allocated-reconciled",
                )
                return 0
            return allocation_deferred(
                arguments,
                attempts,
                "Colab allocation timed out after submission and remained "
                "unconfirmed through bounded discovery polling.",
                pending,
                classification="submission-timeout",
            )

        if CAPACITY_MARKER not in result.stdout:
            emit(result.stdout)
            if replacement:
                assert pending is not None
                return allocation_deferred(
                    arguments,
                    attempts,
                    "The bounded replacement allocation was rejected while the "
                    "original allocation remains unresolved.",
                    pending,
                    classification="replacement-rejected",
                )
            write_receipt(
                arguments.result,
                session=arguments.session,
                attempts=attempts,
                outcome="allocation-failed",
            )
            return exit_status(result.returncode)

        session_state, sessions = reconcile_sessions(
            arguments,
            deadline=deadline if arguments.retry_seconds else None,
        )
        if session_state == "named":
            emit(sessions.stdout)
            clear_pending(arguments)
            arguments.resource_state.write_text("reused\n", encoding="utf-8")
            write_receipt(
                arguments.result,
                session=arguments.session,
                attempts=attempts,
                outcome="reused-after-capacity",
                classification=CAPACITY_MARKER,
            )
            return 0
        if session_state in {"unknown", "error"}:
            emit(sessions.stdout)
            if pending is None:
                pending = new_pending(arguments, origin="capacity-reconciliation")
                pending["allocation_requests"] = attempts
            return allocation_deferred(
                arguments,
                attempts,
                "Colab capacity response could not be reconciled with session discovery.",
                pending,
                classification="capacity-reconciliation-inconclusive",
            )

        if replacement:
            assert pending is not None
            return allocation_deferred(
                arguments,
                attempts,
                "The bounded replacement received a capacity rejection; the "
                "saved allocation will be reconciled again later.",
                pending,
                classification=CAPACITY_MARKER,
            )

        if arguments.retry_seconds == 0:
            emit(result.stdout)
            print(
                "[cloudmake] capacity unavailable: colab "
                f"{CAPACITY_MARKER}; attempt={attempts}; retry disabled",
                file=sys.stderr,
            )
            write_receipt(
                arguments.result,
                session=arguments.session,
                attempts=attempts,
                outcome="capacity-unavailable",
                classification=CAPACITY_MARKER,
            )
            return exit_status(result.returncode)

        now = time.monotonic()
        elapsed = now - started
        remaining = max(0.0, deadline - now)
        if remaining <= 0:
            return capacity_timeout(arguments, attempts, started)

        exponential = min(maximum, base * (2 ** min(attempts - 1, 30)))
        randomized = min(
            maximum, exponential * random.uniform(1 - jitter, 1 + jitter)
        )
        delay = min(remaining, max(0.01, randomized))
        print(
            "[cloudmake] capacity unavailable: colab "
            f"{CAPACITY_MARKER}; attempt={attempts} "
            f"elapsed={duration(elapsed)} remaining={duration(remaining, round_up=True)} "
            f"next={duration(delay, round_up=True)}",
            file=sys.stderr,
            flush=True,
        )
        time.sleep(delay)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Start or reuse a Colab session with classified capacity retry"
    )
    parser.add_argument("--client", required=True)
    parser.add_argument("--session", required=True)
    parser.add_argument("--gpu", default="")
    parser.add_argument("--retry-seconds", required=True, type=int)
    parser.add_argument("--command-timeout", required=True, type=float)
    parser.add_argument("--resource-state", required=True, type=Path)
    parser.add_argument("--pending-state", required=True, type=Path)
    parser.add_argument("--result", required=True, type=Path)
    parser.add_argument("--state-file", type=Path)
    arguments = parser.parse_args()
    if arguments.retry_seconds < 0:
        parser.error("--retry-seconds must not be negative")
    if arguments.command_timeout <= 0:
        parser.error("--command-timeout must be positive")
    arguments.recheck_seconds = tuning(
        "CLOUDMAKE_COLAB_SESSION_RECHECK_SECONDS", 1.0, minimum=0.0
    )
    arguments.reconcile_seconds = tuning(
        "CLOUDMAKE_COLAB_ALLOCATION_RECONCILE_SECONDS", 60.0, minimum=0.01
    )
    arguments.resume_reconcile_seconds = tuning(
        "CLOUDMAKE_COLAB_ALLOCATION_RESUME_SECONDS", 10.0, minimum=0.01
    )
    arguments.replace_after_seconds = tuning(
        "CLOUDMAKE_COLAB_ALLOCATION_REPLACE_AFTER_SECONDS", 120.0, minimum=0.01
    )
    arguments.recovery_retry_seconds = tuning(
        "CLOUDMAKE_COLAB_ALLOCATION_RECOVERY_RETRY_SECONDS", 120.0, minimum=1.0
    )
    arguments.replacement_cooldown_seconds = tuning(
        "CLOUDMAKE_COLAB_ALLOCATION_REPLACEMENT_COOLDOWN_SECONDS",
        600.0,
        minimum=1.0,
    )
    arguments.minimum_empty_observations = int(
        tuning(
            "CLOUDMAKE_COLAB_ALLOCATION_MIN_EMPTY_OBSERVATIONS",
            4.0,
            minimum=2.0,
        )
    )
    arguments.resource_state.parent.mkdir(parents=True, exist_ok=True)
    arguments.pending_state.parent.mkdir(parents=True, exist_ok=True)
    arguments.prior_selection = arguments.resource_state.is_file()
    arguments.resource_state.unlink(missing_ok=True)
    arguments.result.unlink(missing_ok=True)
    try:
        returncode = allocate(arguments)
    except KeyboardInterrupt:
        write_receipt(
            arguments.result,
            session=arguments.session,
            attempts=getattr(arguments, "allocation_attempts", 0),
            outcome="interrupted",
        )
        returncode = 130
    except ValueError as error:
        print(f"[cloudmake] allocation retry configuration error: {error}", file=sys.stderr)
        write_receipt(
            arguments.result,
            session=arguments.session,
            attempts=0,
            outcome="retry-configuration-failed",
        )
        returncode = 2
    if returncode != 0 and arguments.state_file is not None:
        record_operation_failure(arguments.state_file, arguments.result)
    return returncode


if __name__ == "__main__":
    raise SystemExit(main())
