from __future__ import annotations

import os
from pathlib import Path
import sys

import pytest

from conftest import PROJECT_ROOT, run_command, write_executable


HELPER = PROJECT_ROOT / "tools" / "codespaces_state.py"


def fake_gh(path: Path) -> Path:
    executable = path / "gh"
    write_executable(
        executable,
        r'''#!/usr/bin/env python3
import json
import os
import sys
if os.environ.get("FAKE_FAIL"):
    print("provider denied the request", file=sys.stderr)
    raise SystemExit(1)
if os.environ.get("FAKE_MALFORMED"):
    print("not-json")
else:
    print(json.dumps({"state": os.environ.get("FAKE_STATE", "Available")}))
''',
    )
    return executable


@pytest.mark.parametrize(
    ("provider", "execution"),
    [("Available", "reused"), ("Starting", "reused"), ("Shutdown", "started")],
)
def test_codespace_state_classification(
    tmp_path: Path, provider: str, execution: str
) -> None:
    gh = fake_gh(tmp_path)
    output = tmp_path / "state" / "resource-state"
    environment = dict(os.environ, FAKE_STATE=provider)

    result = run_command(
        [
            sys.executable,
            HELPER,
            "--gh",
            gh,
            "--codespace",
            "example",
            "--output",
            output,
        ],
        cwd=tmp_path,
        env=environment,
    )

    assert result.stdout == ""
    assert output.read_text(encoding="utf-8") == f"{execution}\n"


@pytest.mark.parametrize("provider", ["Archived", "Deleted", "Failed", "Unavailable"])
def test_unusable_codespace_state_fails_closed(tmp_path: Path, provider: str) -> None:
    gh = fake_gh(tmp_path)
    output = tmp_path / "resource-state"
    output.write_text("reused\n", encoding="utf-8")

    result = run_command(
        [
            sys.executable,
            HELPER,
            "--gh",
            gh,
            "--codespace",
            "example",
            "--output",
            output,
        ],
        cwd=tmp_path,
        env=dict(os.environ, FAKE_STATE=provider),
        check=False,
    )

    assert result.returncode == 2
    assert provider in result.stdout
    assert not output.exists()


@pytest.mark.parametrize("failure", ["FAKE_FAIL", "FAKE_MALFORMED"])
def test_provider_failure_never_reuses_stale_classification(
    tmp_path: Path, failure: str
) -> None:
    gh = fake_gh(tmp_path)
    output = tmp_path / "resource-state"
    output.write_text("started\n", encoding="utf-8")

    result = run_command(
        [
            sys.executable,
            HELPER,
            "--gh",
            gh,
            "--codespace",
            "example",
            "--output",
            output,
        ],
        cwd=tmp_path,
        env=dict(os.environ, **{failure: "1"}),
        check=False,
    )

    assert result.returncode == 2
    assert not output.exists()
