from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from conftest import PROJECT_ROOT


TOOL = PROJECT_ROOT / "tools" / "gcp_lifecycle.py"


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def vm(status: str, *, machine: str = "e2-micro", accelerator: bool = False):
    value = {
        "name": "workstation",
        "status": status,
        "machineType": f"zones/us-central1-a/machineTypes/{machine}",
    }
    if accelerator:
        value["guestAccelerators"] = [
            {
                "acceleratorType": "zones/us-central1-a/acceleratorTypes/nvidia-rtx-pro-6000",
                "acceleratorCount": 1,
            }
        ]
    return value


def arguments(tmp_path: Path):
    return SimpleNamespace(
        gcloud="gcloud",
        project="example-project",
        zone="us-central1-a",
        instance="workstation",
        output=tmp_path / "resource.json",
        state_file=tmp_path / "resource-state",
        timeout=10.0,
        poll_interval=1.0,
    )


def test_reuses_running_free_tier_shape_without_start(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    module = load("gcp_lifecycle_reuse")
    monkeypatch.setattr(module, "describe", lambda *_: vm("RUNNING"))
    monkeypatch.setattr(
        module,
        "provider",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("unexpected start")
        ),
    )

    assert module.ensure_running(arguments(tmp_path)) == 0

    receipt = json.loads((tmp_path / "resource.json").read_text(encoding="utf-8"))
    assert receipt["resource_state"] == "reused"
    assert receipt["free_tier_compute_shape"] is True
    assert (tmp_path / "resource-state").read_text(encoding="utf-8") == "reused\n"
    output = capsys.readouterr()
    assert "machine=e2-micro" in output.out
    assert "paid-capable" not in output.err


def test_stopped_paid_gpu_starts_once_then_waits(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    module = load("gcp_lifecycle_start")
    states = iter(
        [
            vm("TERMINATED", machine="g4-standard-48", accelerator=True),
            vm("RUNNING", machine="g4-standard-48", accelerator=True),
        ]
    )
    calls: list[list[str]] = []
    monkeypatch.setattr(module, "describe", lambda *_: next(states))

    def provider(_gcloud, command, **_kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(module, "provider", provider)
    monkeypatch.setattr(module.time, "monotonic", lambda: 0.0)

    assert module.ensure_running(arguments(tmp_path)) == 0

    assert [command[2] for command in calls] == ["start"]
    receipt = json.loads((tmp_path / "resource.json").read_text(encoding="utf-8"))
    assert receipt["resource_state"] == "started"
    assert receipt["accelerators"] == ["nvidia-rtx-pro-6000x1"]
    assert receipt["billing_exposure"] == "paid-capable"
    assert "provider billing and quota remain authoritative" in capsys.readouterr().err


@pytest.mark.parametrize("status", ["STOPPING", "SUSPENDING", "REPAIRING"])
def test_ambiguous_start_state_fails_without_mutation(
    tmp_path: Path, monkeypatch, status: str
) -> None:
    module = load(f"gcp_lifecycle_ambiguous_{status.lower()}")
    monkeypatch.setattr(module, "describe", lambda *_: vm(status))
    calls: list[object] = []
    monkeypatch.setattr(module, "provider", lambda *_args, **_kwargs: calls.append(1))

    with pytest.raises(module.LifecycleError, match="ambiguous state"):
        module.ensure_running(arguments(tmp_path))

    assert calls == []
    assert not (tmp_path / "resource-state").exists()


def test_stop_retains_disk_and_waits_for_terminated(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    module = load("gcp_lifecycle_stop")
    states = iter([vm("RUNNING"), vm("STOPPING"), vm("TERMINATED")])
    calls: list[list[str]] = []
    monkeypatch.setattr(module, "describe", lambda *_: next(states))
    monkeypatch.setattr(
        module,
        "provider",
        lambda _gcloud, command, **_kwargs: (
            calls.append(command)
            or subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        ),
    )
    clock = [0.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        module.time, "sleep", lambda delay: clock.__setitem__(0, clock[0] + delay)
    )

    assert module.stop(arguments(tmp_path)) == 0

    assert [command[2] for command in calls] == ["stop"]
    assert (tmp_path / "resource-state").read_text(encoding="utf-8") == "stopped\n"
    assert "disk=retained" in capsys.readouterr().out


def test_provider_error_is_concise_and_preserves_detail(monkeypatch) -> None:
    module = load("gcp_lifecycle_provider_error")
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            ["gcloud"], 1, stdout="", stderr="QUOTA_EXCEEDED"
        ),
    )

    with pytest.raises(module.LifecycleError, match="QUOTA_EXCEEDED"):
        module.describe("gcloud", "project", "zone", "instance")


def test_quota_failure_during_start_never_publishes_running_state(
    tmp_path: Path, monkeypatch
) -> None:
    module = load("gcp_lifecycle_quota_start")
    monkeypatch.setattr(
        module,
        "describe",
        lambda *_: vm("TERMINATED", machine="g4-standard-48", accelerator=True),
    )

    def quota_failure(*_args, **_kwargs):
        raise module.LifecycleError(
            "Google Compute Engine instance start failed: QUOTA_EXCEEDED"
        )

    monkeypatch.setattr(module, "provider", quota_failure)

    with pytest.raises(module.LifecycleError, match="QUOTA_EXCEEDED"):
        module.ensure_running(arguments(tmp_path))

    assert not (tmp_path / "resource.json").exists()
    assert not (tmp_path / "resource-state").exists()
