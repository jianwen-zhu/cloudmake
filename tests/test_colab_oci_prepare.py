from __future__ import annotations

import base64
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

from conftest import PROJECT_ROOT


TOOL = PROJECT_ROOT / "tools" / "colab_oci_prepare.py"


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def control(path: Path) -> None:
    image = "registry.example/tools@sha256:" + "a" * 64
    path.write_text(
        "\n".join(
            (
                base64.urlsafe_b64encode(image.encode()).decode(),
                base64.urlsafe_b64encode(b"[]").decode(),
                "/content/project",
                "/content/cache",
                "Makefile",
            )
        )
        + "\n",
        encoding="utf-8",
    )


def test_missing_base_mount_command_fails_without_package_install(
    tmp_path: Path, monkeypatch
) -> None:
    module = load("colab_oci_prepare_missing_base")
    module.CONTROL = tmp_path / "control"
    module.RESULT = tmp_path / "result.json"
    control(module.CONTROL)
    calls: list[list[str]] = []
    monkeypatch.setattr(
        module.shutil,
        "which",
        lambda name: None if name == "mount" else f"/usr/bin/{name}",
    )
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda command, **kwargs: calls.append(command)
        or subprocess.CompletedProcess(command, 0),
    )

    module.main()

    receipt = json.loads(module.RESULT.read_text(encoding="utf-8"))
    assert receipt["status"] == "infrastructure-failed"
    assert "base VM" in receipt["error"]
    assert "mount" in receipt["error"]
    assert calls == []


def test_installer_requests_only_materialization_packages(
    tmp_path: Path, monkeypatch
) -> None:
    module = load("colab_oci_prepare_packages")
    module.CONTROL = tmp_path / "control"
    module.RESULT = tmp_path / "result.json"
    module.RUNNER = tmp_path / "runner.py"
    control(module.CONTROL)
    calls: list[list[str]] = []
    monkeypatch.setattr(
        module.shutil,
        "which",
        lambda name: None if name in {"skopeo", "umoci"} else f"/usr/bin/{name}",
    )

    def fake_run(command, **kwargs):
        calls.append(command)
        if "--mode" in command:
            module.RESULT.write_text(
                json.dumps({"schema": 1, "mode": "preflight", "status": "ready"}),
                encoding="utf-8",
            )
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    module.main()

    install = next(command for command in calls if command[:2] == ["apt-get", "install"])
    assert "skopeo" in install
    assert "umoci" in install
    assert "mount" not in install
    assert "umount" not in install
    runner = calls[-1]
    assert runner[runner.index("--runtime") + 1] == "chroot"
