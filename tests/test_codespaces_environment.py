from __future__ import annotations

import base64
import importlib.util
import json
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
import sys

from conftest import PROJECT_ROOT, run_command


TOOL = PROJECT_ROOT / "tools" / "codespaces_environment.py"
RESULT_TOOL = PROJECT_ROOT / "tools" / "provider_oci_result.py"
IMAGE = "registry.example/science/tools@sha256:" + "a" * 64


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def encoded(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii")


def arguments(tmp_path: Path, mode: str = "oci") -> SimpleNamespace:
    native_config = tmp_path / "devcontainer.json"
    native_config.write_text('{"name":"anchor"}\n', encoding="utf-8")
    native_dockerfile = tmp_path / "Dockerfile"
    native_dockerfile.write_text("FROM ubuntu:24.04\n", encoding="utf-8")
    return SimpleNamespace(
        gh="gh",
        codespace="example",
        mode=mode,
        image_b64=encoded(IMAGE) if mode == "oci" else "",
        native_config=native_config,
        native_dockerfile=native_dockerfile,
        receipt=tmp_path / "receipt.json",
        timeout=0.1,
    )


def test_generated_environment_is_native_nonroot_and_not_nested() -> None:
    module = load("codespaces_environment_generation")
    dockerfile, configuration_text = module.generated_files(IMAGE)
    configuration = json.loads(configuration_text)

    assert dockerfile.startswith(f"FROM {IMAGE}\n")
    assert configuration["remoteUser"] == "vscode"
    assert "docker-in-docker" not in configuration_text
    assert "privileged" not in configuration
    assert "runArgs" not in configuration
    assert "ghcr.io/devcontainers/features/sshd:1.1.0" in configuration["features"]


def test_image_change_rebuilds_once_then_reuses(tmp_path: Path, monkeypatch) -> None:
    module = load("codespaces_environment_reconcile")
    writes: list[tuple[PurePosixPath, str]] = []
    marker: dict[str, object] = {}
    rebuilds: list[str] = []
    monkeypatch.setattr(
        module, "workspace_root", lambda *_: PurePosixPath("/workspaces/cloudmake")
    )
    monkeypatch.setattr(module, "read_marker", lambda *_: dict(marker))

    def write_remote(_gh, _codespace, path, content):
        writes.append((path, content))
        if path.name == "native-oci-environment.json":
            marker.update(json.loads(content))

    monkeypatch.setattr(module, "write_remote", write_remote)
    monkeypatch.setattr(module, "rebuild", lambda *_: rebuilds.append("rebuild"))
    monkeypatch.setattr(module, "wait_for_ssh", lambda *_: None)
    selected = arguments(tmp_path)

    first = module.reconcile(selected)
    second = module.reconcile(selected)

    assert first["outcome"] == "rebuilt"
    assert second["outcome"] == "reused"
    assert rebuilds == ["rebuild"]
    assert [path.name for path, _ in writes] == [
        "cloudmake-oci.Dockerfile",
        "devcontainer.json",
        "native-oci-environment.json",
        "native-oci-environment.json",
    ]
    assert marker["status"] == "ready"


def test_different_image_replaces_the_single_workstation_environment(
    tmp_path: Path, monkeypatch
) -> None:
    module = load("codespaces_environment_transition")
    marker: dict[str, object] = {}
    rebuilds: list[str] = []
    monkeypatch.setattr(
        module, "workspace_root", lambda *_: PurePosixPath("/workspaces/cloudmake")
    )
    monkeypatch.setattr(module, "read_marker", lambda *_: dict(marker))

    def write_remote(_gh, _codespace, path, content):
        if path.name == "native-oci-environment.json":
            marker.clear()
            marker.update(json.loads(content))

    monkeypatch.setattr(module, "write_remote", write_remote)
    monkeypatch.setattr(module, "rebuild", lambda *_: rebuilds.append("rebuild"))
    monkeypatch.setattr(module, "wait_for_ssh", lambda *_: None)

    first = arguments(tmp_path)
    second = arguments(tmp_path)
    second.image_b64 = encoded(
        "registry.example/science/tools@sha256:" + "b" * 64
    )

    assert module.reconcile(first)["outcome"] == "rebuilt"
    assert module.reconcile(second)["outcome"] == "rebuilt"
    assert module.reconcile(second)["outcome"] == "reused"
    assert rebuilds == ["rebuild", "rebuild"]
    assert marker["image"].endswith("b" * 64)


def test_failed_rebuild_leaves_recoverable_preparing_marker(
    tmp_path: Path, monkeypatch
) -> None:
    module = load("codespaces_environment_failed_rebuild")
    marker: dict[str, object] = {}
    monkeypatch.setattr(
        module, "workspace_root", lambda *_: PurePosixPath("/workspaces/cloudmake")
    )
    monkeypatch.setattr(module, "read_marker", lambda *_: dict(marker))

    def write_remote(_gh, _codespace, path, content):
        if path.name == "native-oci-environment.json":
            marker.clear()
            marker.update(json.loads(content))

    monkeypatch.setattr(module, "write_remote", write_remote)

    def fail_rebuild(*_):
        raise module.EnvironmentError("Codespaces rebuild failed")

    monkeypatch.setattr(module, "rebuild", fail_rebuild)

    try:
        module.reconcile(arguments(tmp_path))
    except module.EnvironmentError as error:
        assert str(error) == "Codespaces rebuild failed"
    else:
        raise AssertionError("failed rebuild unexpectedly succeeded")

    assert marker["status"] == "preparing"
    assert marker["image"] == IMAGE


def test_native_selection_restores_anchor(tmp_path: Path, monkeypatch) -> None:
    module = load("codespaces_environment_native_restore")
    writes: list[tuple[str, str]] = []
    removals: list[str] = []
    monkeypatch.setattr(
        module, "workspace_root", lambda *_: PurePosixPath("/workspaces/cloudmake")
    )
    monkeypatch.setattr(module, "read_marker", lambda *_: {"schema": 1, "image": IMAGE})
    monkeypatch.setattr(
        module,
        "write_remote",
        lambda _gh, _codespace, path, content: writes.append((path.name, content)),
    )
    monkeypatch.setattr(module, "rebuild", lambda *_: None)
    monkeypatch.setattr(module, "wait_for_ssh", lambda *_: None)
    monkeypatch.setattr(
        module,
        "remove_remote",
        lambda _gh, _codespace, path: removals.append(path.name),
    )

    receipt = module.reconcile(arguments(tmp_path, mode="native"))

    assert receipt["outcome"] == "rebuilt"
    assert [name for name, _ in writes] == ["devcontainer.json", "Dockerfile"]
    assert removals == ["native-oci-environment.json"]


def test_provider_native_terminal_receipt_preserves_target_failure(tmp_path: Path) -> None:
    result_path = tmp_path / "result.json"
    completed = run_command(
        [
            sys.executable,
            RESULT_TOOL,
            "--result",
            result_path,
            "--runtime",
            "provider-native",
            "--image-b64",
            encoded(IMAGE),
            "--target-b64",
            encoded("place"),
            "--exit-code",
            "2",
        ],
        cwd=tmp_path,
    )

    assert completed.stdout == ""
    receipt = json.loads(result_path.read_text(encoding="utf-8"))
    assert receipt["status"] == "target-failed"
    assert receipt["target"] == "place"
    assert receipt["exit_code"] == 2
    assert receipt["image_inspection"]["provider_native"] is True
