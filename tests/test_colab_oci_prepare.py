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


def control(
    path: Path,
    *,
    devices: list[str] | None = None,
    runtimes: list[str] | None = None,
    environment: list[str] | None = None,
    host_requirements: dict[str, object] | None = None,
) -> None:
    image = "registry.example/tools@sha256:" + "a" * 64
    lines = [
        base64.urlsafe_b64encode(image.encode()).decode(),
        base64.urlsafe_b64encode(json.dumps(devices or []).encode()).decode(),
        "/content/project",
        "/content/cache",
        "Makefile",
        base64.urlsafe_b64encode(
            json.dumps(runtimes or ["crun"]).encode()
        ).decode(),
    ]
    if environment is not None or host_requirements is not None:
        lines.extend(
            [
                base64.urlsafe_b64encode(
                    json.dumps(environment or []).encode()
                ).decode(),
                base64.urlsafe_b64encode(
                    json.dumps(host_requirements or {}).encode()
                ).decode(),
            ]
        )
    path.write_text(
        "\n".join(lines)
        + "\n",
        encoding="utf-8",
    )


def test_devcontainer_environment_and_requirements_reach_runner(
    tmp_path: Path, monkeypatch
) -> None:
    module = load("colab_oci_prepare_devcontainer")
    module.CONTROL = tmp_path / "control"
    module.RESULT = tmp_path / "result.json"
    module.RUNNER = tmp_path / "runner.py"
    control(
        module.CONTROL,
        environment=["FLOW=smoke"],
        host_requirements={"cpus": 1},
    )
    calls: list[list[str]] = []
    monkeypatch.setattr(module, "generate_colab_nvidia_cdi", lambda *_: None)
    monkeypatch.setattr(module.shutil, "which", lambda name: f"/usr/bin/{name}")

    def fake_run(command, **kwargs):
        calls.append(command)
        module.RESULT.write_text(
            json.dumps({"schema": 1, "mode": "preflight", "status": "ready"}),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    module.main()

    runner = calls[-1]
    assert runner[runner.index("--env") + 1] == "FLOW=smoke"
    assert "--host-requirements-b64" in runner


def test_nonqualified_runtime_is_rejected_without_package_install(
    tmp_path: Path, monkeypatch
) -> None:
    module = load("colab_oci_prepare_missing_base")
    module.CONTROL = tmp_path / "control"
    module.RESULT = tmp_path / "result.json"
    control(module.CONTROL, runtimes=["proot"])
    calls: list[list[str]] = []
    monkeypatch.setattr(
        module.shutil,
        "which",
        lambda name: f"/usr/bin/{name}",
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
    assert "qualified crun profile" in receipt["error"]
    assert calls == []


def test_malformed_device_control_is_rejected_without_package_install(
    tmp_path: Path, monkeypatch
) -> None:
    module = load("colab_oci_prepare_malformed_devices")
    module.CONTROL = tmp_path / "control"
    module.RESULT = tmp_path / "result.json"
    control(module.CONTROL)
    lines = module.CONTROL.read_text(encoding="utf-8").splitlines()
    lines[1] = base64.urlsafe_b64encode(json.dumps({"not": "a list"}).encode()).decode()
    module.CONTROL.write_text("\n".join(lines) + "\n", encoding="utf-8")
    calls: list[list[str]] = []
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda command, **kwargs: calls.append(command),
    )

    module.main()

    receipt = json.loads(module.RESULT.read_text(encoding="utf-8"))
    assert receipt["status"] == "infrastructure-failed"
    assert "CDI device list" in receipt["error"]
    assert calls == []


def test_installer_preflights_packages_runtime_and_devices(
    tmp_path: Path, monkeypatch
) -> None:
    module = load("colab_oci_prepare_packages")
    module.CONTROL = tmp_path / "control"
    module.RESULT = tmp_path / "result.json"
    module.RUNNER = tmp_path / "runner.py"
    control(module.CONTROL, devices=["nvidia.com/gpu=all"])
    calls: list[list[str]] = []
    generated: list[tuple[Path, list[str]]] = []
    monkeypatch.setattr(
        module,
        "generate_colab_nvidia_cdi",
        lambda directory, devices: generated.append((directory, devices)),
    )
    monkeypatch.setattr(
        module.shutil,
        "which",
        lambda name: None if name in {"skopeo", "umoci", "crun"} else f"/usr/bin/{name}",
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
    assert "crun" in install
    assert "mount" not in install
    assert "umount" not in install
    runner = calls[-1]
    assert runner[runner.index("--runtime") + 1] == "auto"
    assert runner[runner.index("--runtime-candidate") + 1] == "crun"
    assert runner[runner.index("--cdi-spec-dir") + 1] == "/content/cache/cdi"
    assert runner[runner.index("--device") + 1] == "nvidia.com/gpu=all"
    assert generated == [(Path("/content/cache/cdi"), ["nvidia.com/gpu=all"])]


def test_colab_generates_transient_nvidia_cdi_from_provider_mounts(
    tmp_path: Path, monkeypatch
) -> None:
    module = load("colab_oci_prepare_nvidia_cdi")
    libraries = tmp_path / "usr-lib64-nvidia"
    binary = tmp_path / "nvidia-smi"
    libraries.mkdir()
    binary.write_text("binary", encoding="utf-8")
    monkeypatch.setattr(module, "NVIDIA_LIBRARY_DIR", libraries)
    monkeypatch.setattr(module, "NVIDIA_SMI", binary)
    monkeypatch.setattr(
        module,
        "colab_nvidia_device_paths",
        lambda: ["/dev/nvidia0", "/dev/nvidiactl", "/dev/nvidia-uvm"],
    )
    directory = tmp_path / "cdi"
    module.generate_colab_nvidia_cdi(directory, ["nvidia.com/gpu=all"])

    payload = json.loads((directory / "cloudmake-colab-nvidia.json").read_text())
    assert payload["kind"] == "nvidia.com/gpu"
    assert payload["devices"][0]["name"] == "all"
    edits = payload["devices"][0]["containerEdits"]
    assert {item["path"] for item in edits["deviceNodes"]} == {
        "/dev/nvidia0", "/dev/nvidiactl", "/dev/nvidia-uvm"
    }
