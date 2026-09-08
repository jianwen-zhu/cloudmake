from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

from conftest import PROJECT_ROOT, run_command


TOOL = PROJECT_ROOT / "tools" / "vm_capabilities.py"


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def profile(*, user_namespace: str = "unusable", bind_mount: str = "unusable") -> dict:
    return {
        "schema": 1,
        "platform": {"system": "linux", "architecture": "x86_64"},
        "identity": {"effective_uid": 1000},
        "resources": {"cpu_count": 2},
        "filesystem": {"executable_files": True, "symbolic_links": True},
        "isolation": {
            "user_namespace": {"status": user_namespace},
            "bind_mount_namespace": {"status": bind_mount},
        },
        "devices": {
            "fuse": {"present": False},
            "kvm": {"present": False},
        },
        "accelerators": {"nvidia": {"status": "unavailable"}},
    }


def test_filesystem_probe_is_bounded_to_workspace(tmp_path: Path) -> None:
    module = load("vm_capabilities_filesystem")
    workspace = tmp_path / "workspace"

    result = module.filesystem_features(workspace)

    assert result["executable_files"] is True
    assert result["symbolic_links"] is True
    assert result["hard_links"] is True
    assert list(workspace.iterdir()) == []


def test_profile_is_machine_readable_and_renderable(tmp_path: Path, capsys) -> None:
    module = load("vm_capabilities_render")
    value = profile()
    path = tmp_path / "profile.json"

    module.atomic_json(path, value)
    module.render(json.loads(path.read_text(encoding="utf-8")))

    output = capsys.readouterr().out
    assert "environment os=linux arch=x86_64" in output
    assert "capabilities filesystem=unknown exec=yes symlink=yes" in output
    assert "nix" not in output.lower()
    assert "oci-clients=none cdi-devices=0" in output
    assert "sif" not in output.lower()
    assert "evidence=observed (not a provider guarantee)" in output


def test_cdi_probe_records_only_standard_qualified_names(tmp_path: Path) -> None:
    module = load("vm_capabilities_cdi")
    static = tmp_path / "etc-cdi"
    dynamic = tmp_path / "run-cdi"
    static.mkdir()
    dynamic.mkdir()
    (static / "nvidia.json").write_text(
        json.dumps(
            {
                "cdiVersion": "1.0.0",
                "kind": "nvidia.com/gpu",
                "devices": [{"name": "0"}, {"name": "all"}],
            }
        ),
        encoding="utf-8",
    )
    (dynamic / "invalid.json").write_text("{broken", encoding="utf-8")

    result = module.cdi_record((static, dynamic))

    assert result["devices"] == ["nvidia.com/gpu=0", "nvidia.com/gpu=all"]
    assert result["files"] == 2
    assert result["json_invalid"] == 1
    serialized = json.dumps(result)
    assert "containerEdits" not in serialized
    assert "env" not in serialized


def test_remote_entrypoint_ignores_jupyter_kernel_arguments(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    module = load("vm_capabilities_jupyter_arguments")
    result = tmp_path / "result.json"
    workspace = tmp_path / "workspace"
    value = profile()
    monkeypatch.setattr(module, "observe", lambda selected: value)
    monkeypatch.setattr(
        module.sys,
        "argv",
        [
            "colab_kernel_launcher.py",
            "-f",
            "/root/.local/share/jupyter/runtime/kernel.json",
        ],
    )

    monkeypatch.setattr(module, "DEFAULT_RESULT", result)
    monkeypatch.setattr(module, "DEFAULT_WORKSPACE", workspace)

    assert module.main() == 0
    assert json.loads(result.read_text(encoding="utf-8")) == value
    assert "environment-profile=" in capsys.readouterr().out


def test_local_mode_and_remote_probe_reject_unknown_arguments(tmp_path: Path) -> None:
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json.dumps(profile()), encoding="utf-8")

    for arguments in (
        ["--render", str(profile_path), "-f", "kernel.json"],
        ["--unexpected"],
    ):
        result = run_command(
            [sys.executable, TOOL, *arguments], cwd=tmp_path, check=False
        )
        assert result.returncode == 2
        assert "error:" in result.stdout
