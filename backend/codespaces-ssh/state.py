#!/usr/bin/env python3
"""Classify a Codespace before the common SSH transport connects to it."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import time
from typing import Any


class CodespaceStateError(RuntimeError):
    """A provider-state response cannot safely drive the SSH connection."""


UNUSABLE_STATES = {"Archived", "Deleted", "Failed", "Unavailable"}
READY_STATES = {"Available"}
STOPPED_STATES = {"Shutdown"}
TRANSITIONAL_STATES = {"Starting", "Rebuilding", "ShuttingDown"}
TRANSIENT_PROVIDER_ERRORS = (
    "connection reset by peer",
    "context deadline exceeded",
    "deadlineexceeded",
    "failed to invoke ssh rpc",
    "timed out while waiting for the codespace to start",
)


def run_provider(
    command: list[str], *, operation: str
) -> subprocess.CompletedProcess[str]:
    delays = (2, 5, 10)
    for attempt in range(1, len(delays) + 2):
        completed = subprocess.run(
            command,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if completed.returncode == 0:
            return completed
        detail = (completed.stderr or completed.stdout).lower()
        if not any(pattern in detail for pattern in TRANSIENT_PROVIDER_ERRORS):
            return completed
        if attempt > len(delays):
            return completed
        delay = delays[attempt - 1]
        print(
            f"[cloudmake] Codespaces {operation} temporarily unavailable; "
            f"retrying in {delay}s (attempt {attempt + 1}/{len(delays) + 1})",
            file=sys.stderr,
        )
        time.sleep(delay)
    raise AssertionError("unreachable")


def atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(value)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def provider_state(gh: str, codespace: str) -> str:
    completed = run_provider(
        [gh, "codespace", "view", "-c", codespace, "--json", "state"],
        operation="state inspection",
    )
    if completed.returncode:
        detail = (completed.stderr or completed.stdout).strip()
        suffix = f": {detail}" if detail else ""
        raise CodespaceStateError(
            f"GitHub could not inspect Codespace {codespace!r}{suffix}"
        )
    try:
        payload: Any = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise CodespaceStateError(
            f"GitHub returned invalid state for Codespace {codespace!r}"
        ) from error
    state = payload.get("state") if isinstance(payload, dict) else None
    if not isinstance(state, str) or not state:
        raise CodespaceStateError(
            f"GitHub returned no state for Codespace {codespace!r}"
        )
    return state


def execution_state(state: str) -> str:
    if state in UNUSABLE_STATES:
        raise CodespaceStateError(
            f"Codespace is not connectable in provider state {state!r}"
        )
    if state in STOPPED_STATES:
        # The following SSH connection wakes the stopped Codespace.
        return "started"
    if state in READY_STATES:
        return "reused"
    raise CodespaceStateError(
        f"Codespace is not ready in provider state {state!r}"
    )


def settled_execution_state(
    gh: str,
    codespace: str,
    *,
    timeout: float,
    poll_interval: float,
) -> str:
    deadline = time.monotonic() + timeout
    state = provider_state(gh, codespace)
    while state in TRANSITIONAL_STATES:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise CodespaceStateError(
                f"Codespace remained in provider state {state!r} past the readiness deadline"
            )
        time.sleep(min(poll_interval, remaining))
        state = provider_state(gh, codespace)
    return execution_state(state)


def ssh_config(gh: str, codespace: str) -> str:
    completed = run_provider(
        [gh, "codespace", "ssh", "--config", "-c", codespace],
        operation="SSH configuration",
    )
    if completed.returncode:
        detail = (completed.stderr or completed.stdout).strip()
        suffix = f": {detail}" if detail else ""
        raise CodespaceStateError(
            f"GitHub could not prepare SSH for Codespace {codespace!r}{suffix}"
        )
    # macOS uses a long per-user TMPDIR and OpenSSH appends a temporary suffix
    # while binding a master socket. Keep this path deliberately short enough
    # for the platform's Unix-domain socket limit.
    control_directory = Path("/tmp") / f"cloudmake-cs-{os.getuid()}"
    try:
        control_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        metadata = control_directory.lstat()
    except OSError as error:
        raise CodespaceStateError(
            f"Cloudmake could not prepare the local SSH control directory: {error}"
        ) from error
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or metadata.st_uid != os.getuid()
    ):
        raise CodespaceStateError(
            "Cloudmake local SSH control directory is not a safe user-owned directory"
        )
    control_directory.chmod(0o700)
    resource = hashlib.sha256(codespace.encode("utf-8")).hexdigest()[:24]
    control_path = control_directory / resource
    base = completed.stdout.rstrip("\n")
    return (
        f"{base}\n"
        "\tControlMaster auto\n"
        "\tControlPersist 60\n"
        f"\tControlPath {control_path}\n"
    )


def stop_and_wait(
    gh: str,
    codespace: str,
    *,
    timeout: float,
    poll_interval: float,
) -> None:
    completed = subprocess.run(
        [gh, "codespace", "stop", "-c", codespace],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    state = provider_state(gh, codespace)
    if completed.returncode and state not in {"ShuttingDown", "Shutdown"}:
        detail = (completed.stderr or completed.stdout).strip()
        suffix = f": {detail}" if detail else ""
        raise CodespaceStateError(
            f"GitHub could not stop Codespace {codespace!r}{suffix}"
        )
    deadline = time.monotonic() + timeout
    while state != "Shutdown":
        if state in UNUSABLE_STATES:
            raise CodespaceStateError(
                f"Codespace became unusable while stopping in provider state {state!r}"
            )
        if state not in READY_STATES | TRANSITIONAL_STATES:
            raise CodespaceStateError(
                f"Codespace returned unexpected stop state {state!r}"
            )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise CodespaceStateError(
                f"Codespace did not reach 'Shutdown' before the stop deadline; last state {state!r}"
            )
        time.sleep(min(poll_interval, remaining))
        state = provider_state(gh, codespace)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--gh", default="gh")
    result.add_argument("--codespace", required=True)
    result.add_argument("--output", type=Path, required=True)
    result.add_argument("--ssh-config", type=Path)
    result.add_argument("--stop", action="store_true")
    result.add_argument("--timeout", type=float, default=300)
    result.add_argument("--poll-interval", type=float, default=2)
    return result


def main() -> int:
    arguments = parser().parse_args()
    arguments.output.unlink(missing_ok=True)
    if arguments.ssh_config is not None:
        arguments.ssh_config.unlink(missing_ok=True)
    try:
        if arguments.stop:
            if arguments.ssh_config is not None:
                raise CodespaceStateError("--stop cannot be combined with --ssh-config")
            stop_and_wait(
                arguments.gh,
                arguments.codespace,
                timeout=arguments.timeout,
                poll_interval=arguments.poll_interval,
            )
            atomic_text(arguments.output, "stopped")
        else:
            state = settled_execution_state(
                arguments.gh,
                arguments.codespace,
                timeout=arguments.timeout,
                poll_interval=arguments.poll_interval,
            )
            if arguments.ssh_config is not None:
                atomic_text(
                    arguments.ssh_config,
                    ssh_config(arguments.gh, arguments.codespace),
                )
            atomic_text(arguments.output, state)
    except (CodespaceStateError, OSError) as error:
        arguments.output.unlink(missing_ok=True)
        if arguments.ssh_config is not None:
            arguments.ssh_config.unlink(missing_ok=True)
        print(f"cloudmake: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
