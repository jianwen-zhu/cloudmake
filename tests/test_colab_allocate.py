from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from conftest import PROJECT_ROOT, write_executable


ALLOCATE = PROJECT_ROOT / "backend" / "colab-notebook" / "allocate.py"


def allocator_command(
    client: Path,
    resource_state: Path,
    receipt: Path,
    *,
    timeout: str = "1",
) -> list[str]:
    return [
        sys.executable,
        str(ALLOCATE),
        "--client",
        str(client),
        "--session",
        "test-session",
        "--retry-seconds",
        "0",
        "--command-timeout",
        timeout,
        "--resource-state",
        str(resource_state),
        "--pending-state",
        str(resource_state.with_name("allocation-pending.json")),
        "--result",
        str(receipt),
    ]


def recovery_environment(**values: str) -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "CLOUDMAKE_COLAB_SESSION_RECHECK_SECONDS": "0.01",
            "CLOUDMAKE_COLAB_ALLOCATION_RECONCILE_SECONDS": "0.15",
            "CLOUDMAKE_COLAB_ALLOCATION_RESUME_SECONDS": "0.1",
            "CLOUDMAKE_COLAB_ALLOCATION_REPLACE_AFTER_SECONDS": "10",
            "CLOUDMAKE_COLAB_ALLOCATION_RECOVERY_RETRY_SECONDS": "1",
            "CLOUDMAKE_COLAB_ALLOCATION_REPLACEMENT_COOLDOWN_SECONDS": "1",
            "CLOUDMAKE_COLAB_ALLOCATION_MIN_EMPTY_OBSERVATIONS": "2",
            **values,
        }
    )
    return environment


def test_timed_out_allocation_adopts_late_named_session(tmp_path: Path) -> None:
    state = tmp_path / "provider"
    client = write_executable(
        tmp_path / "colab",
        r'''#!/usr/bin/env python3
import os
import sys
import time
from pathlib import Path
state = Path(os.environ["FAKE_STATE"])
if sys.argv[1] == "sessions":
    if state.exists() and time.time() - float(state.read_text()) >= 0.05:
        print("[test-session] running")
    raise SystemExit(0)
if sys.argv[1] == "new":
    state.write_text(str(time.time()))
    time.sleep(2)
raise SystemExit(2)
''',
    )
    resource_state = tmp_path / "resource-state"
    receipt = tmp_path / "allocation.json"
    environment = recovery_environment(
        FAKE_STATE=str(state),
        CLOUDMAKE_COLAB_ALLOCATION_RECONCILE_SECONDS="0.4",
    )

    result = subprocess.run(
        allocator_command(client, resource_state, receipt, timeout="0.5"),
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )

    assert result.returncode == 0
    assert resource_state.read_text(encoding="utf-8") == "started\n"
    assert json.loads(receipt.read_text(encoding="utf-8"))["outcome"] == "allocated-reconciled"
    assert not (tmp_path / "allocation-pending.json").exists()


def test_next_invocation_resumes_and_adopts_late_session(tmp_path: Path) -> None:
    log = tmp_path / "colab.jsonl"
    client = write_executable(
        tmp_path / "colab",
        r'''#!/usr/bin/env python3
import json
import os
import sys
import time
from pathlib import Path
with Path(os.environ["FAKE_LOG"]).open("a", encoding="utf-8") as stream:
    stream.write(json.dumps(sys.argv[1:]) + "\n")
if sys.argv[1] == "sessions":
    if os.environ.get("FAKE_VISIBLE"):
        print("[test-session] running")
    raise SystemExit(0)
if sys.argv[1] == "new":
    time.sleep(2)
raise SystemExit(2)
''',
    )
    resource_state = tmp_path / "resource-state"
    receipt = tmp_path / "allocation.json"
    environment = recovery_environment(FAKE_LOG=str(log))

    first = subprocess.run(
        allocator_command(client, resource_state, receipt, timeout="0.5"),
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert first.returncode == 75
    assert (tmp_path / "allocation-pending.json").is_file()

    environment["FAKE_VISIBLE"] = "1"
    second = subprocess.run(
        allocator_command(client, resource_state, receipt, timeout="0.5"),
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )

    assert second.returncode == 0
    assert resource_state.read_text(encoding="utf-8") == "reused\n"
    assert json.loads(receipt.read_text(encoding="utf-8"))["outcome"] == "recovered-late-session"
    commands = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert [command[0] for command in commands].count("new") == 1
    assert not (tmp_path / "allocation-pending.json").exists()


def test_discovery_errors_preserve_pending_attempt_without_replacement(
    tmp_path: Path,
) -> None:
    log = tmp_path / "colab.jsonl"
    submitted = tmp_path / "submitted"
    client = write_executable(
        tmp_path / "colab",
        r'''#!/usr/bin/env python3
import json
import os
import sys
import time
from pathlib import Path
log = Path(os.environ["FAKE_LOG"])
submitted = Path(os.environ["FAKE_SUBMITTED"])
with log.open("a", encoding="utf-8") as stream:
    stream.write(json.dumps(sys.argv[1:]) + "\n")
if sys.argv[1] == "sessions":
    if submitted.exists():
        print("session discovery unavailable")
        raise SystemExit(1)
    raise SystemExit(0)
if sys.argv[1] == "new":
    submitted.touch()
    time.sleep(2)
raise SystemExit(2)
''',
    )
    resource_state = tmp_path / "resource-state"
    receipt = tmp_path / "allocation.json"
    environment = recovery_environment(
        FAKE_LOG=str(log),
        FAKE_SUBMITTED=str(submitted),
        CLOUDMAKE_COLAB_ALLOCATION_REPLACE_AFTER_SECONDS="0.01",
    )

    first = subprocess.run(
        allocator_command(client, resource_state, receipt, timeout="0.5"),
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    second = subprocess.run(
        allocator_command(client, resource_state, receipt, timeout="0.5"),
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )

    assert first.returncode == second.returncode == 75
    assert "Try later" in second.stdout
    commands = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert [command[0] for command in commands].count("new") == 1
    pending = json.loads((tmp_path / "allocation-pending.json").read_text(encoding="utf-8"))
    assert pending["allocation_requests"] == 1


def test_replacement_is_bounded_after_repeated_empty_discovery(tmp_path: Path) -> None:
    log = tmp_path / "colab.jsonl"
    attempts_file = tmp_path / "attempts"
    client = write_executable(
        tmp_path / "colab",
        r'''#!/usr/bin/env python3
import json
import os
import sys
import time
from pathlib import Path
log = Path(os.environ["FAKE_LOG"])
attempts_file = Path(os.environ["FAKE_ATTEMPTS"])
with log.open("a", encoding="utf-8") as stream:
    stream.write(json.dumps(sys.argv[1:]) + "\n")
if sys.argv[1] == "sessions":
    raise SystemExit(0)
if sys.argv[1] == "new":
    attempts = int(attempts_file.read_text()) + 1 if attempts_file.exists() else 1
    attempts_file.write_text(str(attempts))
    time.sleep(2)
raise SystemExit(2)
''',
    )
    resource_state = tmp_path / "resource-state"
    receipt = tmp_path / "allocation.json"
    environment = recovery_environment(
        FAKE_LOG=str(log),
        FAKE_ATTEMPTS=str(attempts_file),
        CLOUDMAKE_COLAB_ALLOCATION_REPLACE_AFTER_SECONDS="0.05",
    )

    first = subprocess.run(
        allocator_command(client, resource_state, receipt, timeout="0.5"),
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    time.sleep(0.06)
    second = subprocess.run(
        allocator_command(client, resource_state, receipt, timeout="0.5"),
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    third = subprocess.run(
        allocator_command(client, resource_state, receipt, timeout="0.5"),
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )

    assert first.returncode == second.returncode == third.returncode == 75
    assert "one allowed replacement for this recovery window" in second.stdout
    assert "Try later" in third.stdout
    assert attempts_file.read_text() == "2"
    time.sleep(1.05)
    fourth = subprocess.run(
        allocator_command(client, resource_state, receipt, timeout="0.5"),
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert fourth.returncode == 75
    assert "one allowed replacement for this recovery window" in fourth.stdout
    assert attempts_file.read_text() == "3"
    pending = json.loads((tmp_path / "allocation-pending.json").read_text(encoding="utf-8"))
    assert pending["allocation_requests"] == 3


def test_timed_out_allocation_is_deferred_and_never_resubmitted(tmp_path: Path) -> None:
    log = tmp_path / "colab.jsonl"
    client = write_executable(
        tmp_path / "colab",
        r'''#!/usr/bin/env python3
import json
import os
import sys
import time
from pathlib import Path
with Path(os.environ["FAKE_LOG"]).open("a", encoding="utf-8") as stream:
    stream.write(json.dumps(sys.argv[1:]) + "\n")
if sys.argv[1] == "sessions":
    raise SystemExit(0)
if sys.argv[1] == "new":
    time.sleep(2)
raise SystemExit(2)
''',
    )
    receipt = tmp_path / "allocation.json"
    resource_state = tmp_path / "resource-state"
    environment = os.environ.copy()
    environment.update(
        {
            "FAKE_LOG": str(log),
            "CLOUDMAKE_COLAB_SESSION_RECHECK_SECONDS": "0",
            "CLOUDMAKE_COLAB_ALLOCATION_RECONCILE_SECONDS": "0.2",
            "CLOUDMAKE_COLAB_ALLOCATION_RESUME_SECONDS": "0.1",
            "CLOUDMAKE_COLAB_ALLOCATION_REPLACE_AFTER_SECONDS": "0.2",
            "CLOUDMAKE_COLAB_ALLOCATION_RECOVERY_RETRY_SECONDS": "1",
            "CLOUDMAKE_COLAB_ALLOCATION_MIN_EMPTY_OBSERVATIONS": "2",
        }
    )

    result = subprocess.run(
        allocator_command(client, resource_state, receipt, timeout="0.5"),
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )

    assert result.returncode == 75
    assert "Try later" in result.stdout
    assert "cloudmake -b colab --retry-for=1s --start" in result.stdout
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert payload["outcome"] == "allocation-deferred"
    assert payload["classification"] == "submission-timeout"
    commands = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert [command[0] for command in commands].count("new") == 1
    assert [command[0] for command in commands].count("sessions") >= 2
    assert not resource_state.exists()
    assert (tmp_path / "allocation-pending.json").is_file()


def test_unnamed_session_blocks_new_allocation(tmp_path: Path) -> None:
    log = tmp_path / "colab.jsonl"
    client = write_executable(
        tmp_path / "colab",
        r'''#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path
with Path(os.environ["FAKE_LOG"]).open("a", encoding="utf-8") as stream:
    stream.write(json.dumps(sys.argv[1:]) + "\n")
if sys.argv[1] == "sessions":
    print("[?] T4 running")
    raise SystemExit(0)
raise SystemExit("new must not be called")
''',
    )
    receipt = tmp_path / "allocation.json"
    resource_state = tmp_path / "resource-state"
    environment = os.environ.copy()
    environment["FAKE_LOG"] = str(log)

    result = subprocess.run(
        allocator_command(client, resource_state, receipt),
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )

    assert result.returncode == 75
    assert "unnamed session" in result.stdout
    commands = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert [command[0] for command in commands] == ["sessions"]


def test_prior_session_gets_visibility_recheck_before_allocation(tmp_path: Path) -> None:
    counter = tmp_path / "count"
    client = write_executable(
        tmp_path / "colab",
        r'''#!/usr/bin/env python3
import os
import sys
from pathlib import Path
counter = Path(os.environ["FAKE_COUNT"])
if sys.argv[1] == "sessions":
    count = int(counter.read_text()) + 1 if counter.exists() else 1
    counter.write_text(str(count))
    if count > 1:
        print("[test-session] running")
    raise SystemExit(0)
raise SystemExit("new must not be called")
''',
    )
    receipt = tmp_path / "allocation.json"
    resource_state = tmp_path / "resource-state"
    resource_state.write_text("reused\n", encoding="utf-8")
    environment = os.environ.copy()
    environment.update(
        {
            "FAKE_COUNT": str(counter),
            "CLOUDMAKE_COLAB_SESSION_RECHECK_SECONDS": "0",
        }
    )

    result = subprocess.run(
        allocator_command(client, resource_state, receipt),
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )

    assert result.returncode == 0
    assert counter.read_text() == "2"
    assert resource_state.read_text(encoding="utf-8") == "reused\n"
    assert json.loads(receipt.read_text(encoding="utf-8"))["outcome"] == "reused"


def test_interrupt_stops_capacity_wait_without_provider_cleanup(
    tmp_path: Path,
) -> None:
    log = tmp_path / "colab.jsonl"
    client = write_executable(
        tmp_path / "colab",
        r'''#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

with Path(os.environ["FAKE_LOG"]).open("a", encoding="utf-8") as stream:
    stream.write(json.dumps(sys.argv[1:]) + "\n")
if sys.argv[1] == "sessions":
    raise SystemExit(0)
if sys.argv[1] == "new":
    print("HTTP 412: TooManyAssignmentsError")
    raise SystemExit(1)
raise SystemExit(f"unexpected command: {sys.argv[1]}")
''',
    )
    receipt = tmp_path / "allocation.json"
    resource_state = tmp_path / "resource-state"
    environment = os.environ.copy()
    environment.update(
        {
            "FAKE_LOG": str(log),
            "CLOUDMAKE_RETRY_BASE_SECONDS": "10",
            "CLOUDMAKE_RETRY_MAX_SECONDS": "10",
            "CLOUDMAKE_RETRY_JITTER": "0",
            "CLOUDMAKE_COLAB_SESSION_RECHECK_SECONDS": "0",
        }
    )
    process = subprocess.Popen(
        [
            sys.executable,
            str(ALLOCATE),
            "--client",
            str(client),
            "--session",
            "interrupt-test",
            "--retry-seconds",
            "3600",
            "--command-timeout",
            "2",
            "--resource-state",
            str(resource_state),
            "--pending-state",
            str(tmp_path / "allocation-pending.json"),
            "--result",
            str(receipt),
        ],
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    assert process.stdout is not None
    progress = process.stdout.readline()
    assert "capacity unavailable" in progress

    process.send_signal(signal.SIGINT)
    remainder, _ = process.communicate(timeout=5)

    assert process.returncode == 130
    assert "Traceback" not in progress + remainder
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert payload["attempts"] == 1
    assert payload["outcome"] == "interrupted"
    commands = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert [command[0] for command in commands].count("new") == 1
    assert [command[0] for command in commands].count("sessions") == 4
    assert not resource_state.exists()
