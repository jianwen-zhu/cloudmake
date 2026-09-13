from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys

import pytest

from conftest import PROJECT_ROOT, run_command, write_executable


HELPER = PROJECT_ROOT / "tools" / "codespaces_state.py"


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, HELPER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


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
if sys.argv[1:3] == ["codespace", "ssh"]:
    print("Host fake-codespace")
    print("  HostName localhost")
    print("  User vscode")
elif os.environ.get("FAKE_MALFORMED"):
    print("not-json")
else:
    print(json.dumps({"state": os.environ.get("FAKE_STATE", "Available")}))
''',
    )
    return executable


@pytest.mark.parametrize(
    ("provider", "execution"),
    [("Available", "reused"), ("Shutdown", "started")],
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


@pytest.mark.parametrize(
    ("states", "execution"),
    [(["ShuttingDown", "Shutdown"], "started"), (["Starting", "Available"], "reused")],
)
def test_transitional_state_is_settled_before_ssh(
    monkeypatch, states: list[str], execution: str
) -> None:
    module = load(f"codespaces_state_transition_{execution}")
    observed = iter(states)
    clock = [0.0]
    monkeypatch.setattr(module, "provider_state", lambda *_: next(observed))
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        module.time, "sleep", lambda duration: clock.__setitem__(0, clock[0] + duration)
    )

    assert (
        module.settled_execution_state(
            "gh", "example", timeout=10, poll_interval=1
        )
        == execution
    )


def test_state_and_ssh_config_are_published_together(tmp_path: Path) -> None:
    gh = fake_gh(tmp_path)
    output = tmp_path / "resource-state"
    config = tmp_path / "ssh-config"

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
            "--ssh-config",
            config,
        ],
        cwd=tmp_path,
    )

    assert result.stdout == ""
    assert output.read_text(encoding="utf-8") == "reused\n"
    config_text = config.read_text(encoding="utf-8")
    assert "Host fake-codespace" in config_text
    assert "ControlPersist 60" in config_text
    assert f"ControlPath /tmp/cloudmake-cs-{os.getuid()}/" in config_text


def test_stop_waits_for_provider_confirmed_shutdown(monkeypatch) -> None:
    module = load("codespaces_state_stop_wait")
    states = iter(["Available", "ShuttingDown", "Shutdown"])
    clock = [0.0]
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *_args, **_kwargs: module.subprocess.CompletedProcess(
            ["gh", "codespace", "stop"], 0, stdout="", stderr=""
        ),
    )
    monkeypatch.setattr(module, "provider_state", lambda *_: next(states))
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        module.time, "sleep", lambda duration: clock.__setitem__(0, clock[0] + duration)
    )

    module.stop_and_wait("gh", "example", timeout=10, poll_interval=1)

    assert clock[0] == 2


def test_ambiguous_stop_error_is_accepted_only_after_provider_transition(
    monkeypatch,
) -> None:
    module = load("codespaces_state_stop_ambiguity")
    states = iter(["ShuttingDown", "Shutdown"])
    clock = [0.0]
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *_args, **_kwargs: module.subprocess.CompletedProcess(
            ["gh", "codespace", "stop"],
            1,
            stdout="",
            stderr="connection reset by peer",
        ),
    )
    monkeypatch.setattr(module, "provider_state", lambda *_: next(states))
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        module.time, "sleep", lambda duration: clock.__setitem__(0, clock[0] + duration)
    )

    module.stop_and_wait("gh", "example", timeout=10, poll_interval=1)

    assert clock[0] == 1


def test_provider_retry_is_bounded_to_classified_transient_failures(
    monkeypatch, capsys
) -> None:
    module = load("codespaces_state_provider_retry")
    results = iter(
        [
            module.subprocess.CompletedProcess(
                ["gh"], 1, stdout="", stderr="connection reset by peer"
            ),
            module.subprocess.CompletedProcess(
                ["gh"], 1, stdout="", stderr="rpc error: DeadlineExceeded"
            ),
            module.subprocess.CompletedProcess(["gh"], 0, stdout="ok", stderr=""),
        ]
    )
    delays: list[int] = []
    monkeypatch.setattr(module.subprocess, "run", lambda *_args, **_kwargs: next(results))
    monkeypatch.setattr(module.time, "sleep", delays.append)

    completed = module.run_provider(["gh"], operation="test")

    assert completed.stdout == "ok"
    assert delays == [2, 5]
    assert "attempt 2/4" in capsys.readouterr().err


def test_provider_retry_rejects_authentication_failure_immediately(
    monkeypatch,
) -> None:
    module = load("codespaces_state_provider_no_retry")
    calls: list[list[str]] = []

    def fail(command, **_kwargs):
        calls.append(command)
        return module.subprocess.CompletedProcess(
            command, 1, stdout="", stderr="authentication required"
        )

    monkeypatch.setattr(module.subprocess, "run", fail)

    completed = module.run_provider(["gh"], operation="test")

    assert completed.returncode == 1
    assert calls == [["gh"]]


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
