from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

from conftest import PROJECT_ROOT


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
    assert "oci" not in output.lower()
    assert "sif" not in output.lower()
    assert "evidence=observed (not a provider guarantee)" in output


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
            "--workspace",
            str(workspace),
            "--result",
            str(result),
            "-f",
            "/root/.local/share/jupyter/runtime/kernel.json",
        ],
    )

    assert module.main() == 0
    assert json.loads(result.read_text(encoding="utf-8")) == value
    assert "environment-profile=" in capsys.readouterr().out
