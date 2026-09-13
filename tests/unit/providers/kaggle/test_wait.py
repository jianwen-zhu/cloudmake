from __future__ import annotations

import sys
import time
from pathlib import Path

from conftest import PROJECT_ROOT, run_command, write_executable


SCRIPT = PROJECT_ROOT / "tools" / "kaggle_wait.py"


def fake_status_client(path: Path, statuses: list[str], returncodes: list[int] | None = None) -> Path:
    codes = returncodes or [0] * len(statuses)
    return write_executable(
        path,
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "from pathlib import Path\n"
        f"statuses = {statuses!r}\n"
        f"codes = {codes!r}\n"
        "state = Path(__file__).with_suffix('.count')\n"
        "count = int(state.read_text()) if state.exists() else 0\n"
        "state.write_text(str(count + 1))\n"
        "index = min(count, len(statuses) - 1)\n"
        "print(statuses[index])\n"
        "raise SystemExit(codes[index])\n",
    )


def wait(client: Path, tmp_path: Path, timeout: str = "1"):
    return run_command(
        [
            "python3", SCRIPT, "--kaggle", client, "--kernel", "tester/job",
            "--timeout", timeout, "--poll", "0.01",
        ],
        cwd=tmp_path,
        check=False,
        timeout=3,
    )


def test_wait_succeeds_after_running_status(tmp_path: Path) -> None:
    client = fake_status_client(tmp_path / "kaggle", ["running", "running", "complete"])
    result = wait(client, tmp_path)
    assert result.returncode == 0
    assert result.stdout.count("running") == 1
    assert "complete" in result.stdout


def test_wait_tolerates_transient_client_error(tmp_path: Path) -> None:
    client = fake_status_client(
        tmp_path / "kaggle", ["service temporarily unavailable", "complete"], [2, 0]
    )
    result = wait(client, tmp_path)
    assert result.returncode == 0
    assert "complete" in result.stdout


def test_wait_fails_immediately_for_terminal_failure(tmp_path: Path) -> None:
    client = fake_status_client(tmp_path / "kaggle", ["running", "error: image build failed"])
    result = wait(client, tmp_path)
    assert result.returncode == 1
    assert "did not complete successfully" in result.stdout


def test_wait_returns_timeout_exit_code(tmp_path: Path) -> None:
    client = fake_status_client(tmp_path / "kaggle", ["running"])
    result = wait(client, tmp_path, timeout="0.05")
    assert result.returncode == 124
    assert "Timed out waiting for tester/job" in result.stdout


def test_wait_timeout_also_bounds_a_hung_status_probe(tmp_path: Path) -> None:
    client = write_executable(
        tmp_path / "kaggle",
        "#!/usr/bin/env python3\nimport time\ntime.sleep(5)\n",
    )

    started = time.monotonic()
    result = wait(client, tmp_path, timeout="0.1")
    elapsed = time.monotonic() - started

    assert result.returncode == 124
    assert elapsed < 1
    assert "status probe timed out" in result.stdout


def test_wait_rejects_nonpositive_or_nonfinite_timing_values(tmp_path: Path) -> None:
    client = fake_status_client(tmp_path / "kaggle", ["running"])
    for timeout, poll in (("0", "1"), ("1", "-1"), ("nan", "1")):
        result = run_command(
            [
                sys.executable,
                SCRIPT,
                "--kaggle",
                client,
                "--kernel",
                "owner/kernel",
                "--timeout",
                timeout,
                "--poll",
                poll,
            ],
            cwd=tmp_path,
            check=False,
        )

        assert result.returncode == 2
        assert "greater than zero" in result.stdout
