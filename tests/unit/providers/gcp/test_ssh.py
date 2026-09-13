from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from conftest import PROJECT_ROOT


TOOL = PROJECT_ROOT / "backend" / "gcp-compute-ssh" / "ssh.py"


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def arguments(tmp_path: Path):
    return SimpleNamespace(
        gcloud="gcloud",
        project="example-project",
        zone="us-central1-a",
        instance="workstation",
        tunnel_through_iap=False,
        create_wrapper=tmp_path / "gcp-ssh",
        control_directory=tmp_path / "control",
        python=sys.executable,
    )


def test_remote_command_and_forwarding_are_preserved(
    tmp_path: Path, monkeypatch
) -> None:
    module = load("gcp_ssh_execute")
    observed: list[list[str]] = []
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda command, **_kwargs: (
            observed.append(command) or subprocess.CompletedProcess(command, 0)
        ),
    )
    selected = arguments(tmp_path)
    selected.tunnel_through_iap = True

    assert (
        module.execute(
            selected,
            [
                "-o",
                "ExitOnForwardFailure=yes",
                "-L",
                "8080:127.0.0.1:8080",
                "workstation",
                "sh",
                "-c",
                "make smoke",
            ],
        )
        == 0
    )

    command = observed[0]
    assert command[:4] == ["gcloud", "compute", "ssh", "workstation"]
    assert "--tunnel-through-iap" in command
    assert command[command.index("--command") + 1] == "sh -c 'make smoke'"
    separator = command.index("--")
    assert command[separator + 1 :] == [
        "-o",
        "ExitOnForwardFailure=yes",
        "-L",
        "8080:127.0.0.1:8080",
    ]


def test_rsync_server_arguments_become_one_remote_command(
    tmp_path: Path, monkeypatch
) -> None:
    module = load("gcp_ssh_rsync")
    observed: list[list[str]] = []
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda command, **_kwargs: (
            observed.append(command) or subprocess.CompletedProcess(command, 0)
        ),
    )

    module.execute(
        arguments(tmp_path),
        [
            "workstation",
            "rsync",
            "--server",
            "-logDtpre.iLsfxCIvu",
            ".",
            ".cloudmake/src/",
        ],
    )

    remote = observed[0][observed[0].index("--command") + 1]
    assert remote == "rsync --server -logDtpre.iLsfxCIvu . .cloudmake/src/"


def test_wrong_host_fails_closed(tmp_path: Path) -> None:
    module = load("gcp_ssh_wrong_host")
    with pytest.raises(module.AdapterError, match="does not match"):
        module.split_ssh(["another-host", "true"], "workstation")


def test_generated_wrapper_contains_identifiers_but_no_credentials(
    tmp_path: Path,
) -> None:
    module = load("gcp_ssh_wrapper")
    selected = arguments(tmp_path)
    assert module.create_wrapper(selected) == 0

    source = selected.create_wrapper.read_text(encoding="utf-8")
    assert "example-project" in source
    assert "us-central1-a" in source
    assert "workstation" in source
    assert "token" not in source.lower()
    assert "credential" not in source.lower()
    assert selected.create_wrapper.stat().st_mode & 0o077 == 0
    assert selected.control_directory.stat().st_mode & 0o077 == 0


def test_generated_wrapper_rejects_unsafe_control_directory(tmp_path: Path) -> None:
    module = load("gcp_ssh_unsafe_control")
    selected = arguments(tmp_path)
    target = tmp_path / "elsewhere"
    target.mkdir()
    selected.control_directory.symlink_to(target, target_is_directory=True)

    with pytest.raises(module.AdapterError, match="safe user-owned"):
        module.create_wrapper(selected)


def test_readiness_retries_before_success(tmp_path: Path, monkeypatch, capsys) -> None:
    module = load("gcp_ssh_readiness_success")
    selected = arguments(tmp_path)
    selected.timeout = 10.0
    selected.poll_interval = 1.0
    results = iter(
        [
            subprocess.CompletedProcess([], 255, stdout="", stderr="not ready"),
            subprocess.CompletedProcess([], 255, stdout="", stderr="not ready"),
            subprocess.CompletedProcess([], 0, stdout="", stderr=""),
        ]
    )
    clock = [0.0]
    monkeypatch.setattr(module.subprocess, "run", lambda *_args, **_kwargs: next(results))
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        module.time, "sleep", lambda delay: clock.__setitem__(0, clock[0] + delay)
    )

    assert module.wait_ready(selected) == 0
    output = capsys.readouterr()
    assert "ssh=waiting" in output.err
    assert "ssh=ready attempt=3" in output.out


def test_readiness_timeout_is_bounded_and_preserves_detail(
    tmp_path: Path, monkeypatch
) -> None:
    module = load("gcp_ssh_readiness_timeout")
    selected = arguments(tmp_path)
    selected.timeout = 2.0
    selected.poll_interval = 1.0
    clock = [0.0]
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            [], 255, stdout="", stderr="IAP tunnel unavailable"
        ),
    )
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        module.time, "sleep", lambda delay: clock.__setitem__(0, clock[0] + delay)
    )

    with pytest.raises(module.AdapterError, match="IAP tunnel unavailable"):
        module.wait_ready(selected)

    assert clock[0] == 2.0


def test_cli_reports_expected_interrupt_without_traceback(monkeypatch, capsys) -> None:
    module = load("gcp_ssh_interrupt")
    monkeypatch.setattr(
        module,
        "main",
        lambda: (_ for _ in ()).throw(KeyboardInterrupt()),
    )

    assert module.cli() == 130
    assert capsys.readouterr().err == "cloudmake: GCP SSH operation interrupted\n"
