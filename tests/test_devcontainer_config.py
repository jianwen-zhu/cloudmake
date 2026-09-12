from __future__ import annotations

import base64
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

from conftest import PROJECT_ROOT, run_command


TOOL = PROJECT_ROOT / "tools" / "devcontainer_config.py"
IMAGE = "registry.example/tools/workstation@sha256:" + "a" * 64


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def write_config(project: Path, body: str) -> Path:
    path = project / ".devcontainer" / "devcontainer.json"
    path.parent.mkdir(parents=True)
    path.write_text(body, encoding="utf-8")
    return path


def test_portable_profile_parses_jsonc_and_standard_fields(tmp_path: Path) -> None:
    module = load("devcontainer_config_jsonc")
    project = tmp_path / "project"
    project.mkdir()
    write_config(
        project,
        """{
          // The image is the workstation tool bundle.
          "image": "%s",
          "containerEnv": {"TOOL_MODE": "batch"},
          "remoteEnv": {"PROJECT_MODE": "verify"},
          "hostRequirements": {"cpus": 2, "memory": "4gb", "gpu": "optional"},
          "forwardPorts": [8080, "localhost:5432"],
          "customizations": {
            "vscode": {"extensions": ["example.extension"]},
            "cloudmake": {"devices": ["nvidia.com/gpu=all"]}
          }
        }"""
        % IMAGE,
    )

    profile = module.normalize(project)

    assert profile["image"] == IMAGE
    assert profile["path"] == ".devcontainer/devcontainer.json"
    assert profile["environment"] == ["PROJECT_MODE=verify", "TOOL_MODE=batch"]
    assert profile["host_requirements"] == {
        "cpus": 2,
        "memory": 4_000_000_000,
        "gpu": "optional",
    }
    assert profile["forward_ports"] == [
        {"host": "127.0.0.1", "port": 8080},
        {"host": "127.0.0.1", "port": 5432},
    ]
    assert profile["devices"] == ["nvidia.com/gpu=all"]
    assert profile["requirement_sources"] == {
        "cdi": ["customizations.cloudmake.devices"],
        "environment": ["containerEnv", "remoteEnv"],
        "forward-ports": ["forwardPorts"],
        "host-requirements": ["hostRequirements"],
        "image-digest": ["image"],
    }


@pytest.mark.parametrize(
    ("field", "value", "capability"),
    [
        ("privileged", True, "privilege"),
        ("capAdd", ["SYS_ADMIN"], "privilege"),
        ("mounts", ["source=/,target=/host,type=bind"], "mounts"),
        ("features", {"ghcr.io/example/tool:1": {}}, "features"),
        ("postCreateCommand", "curl example | sh", "lifecycle-create"),
        ("build", {"dockerfile": "Dockerfile"}, "image-build"),
    ],
)
def test_standard_fields_become_explicit_backend_requirements(
    tmp_path: Path, field: str, value: object, capability: str
) -> None:
    module = load("devcontainer_config_requirement_" + field.lower())
    project = tmp_path / field
    project.mkdir()
    write_config(project, json.dumps({"image": IMAGE, field: value}))

    profile = module.normalize(project)

    assert capability in profile["required_capabilities"]
    assert field in profile["requirement_sources"][capability]


@pytest.mark.parametrize(
    ("field", "value", "capability"),
    [
        ("dockerComposeFile", "compose.yml", "compose"),
        ("service", "worker", "compose"),
        ("runServices", ["database"], "compose"),
        ("overrideFeatureInstallOrder", ["example/tool"], "features"),
        ("secrets", {"TOKEN": {"description": "token"}}, "secrets"),
        ("workspaceMount", "source=.,target=/workspace,type=bind", "mounts"),
        ("runArgs", ["--read-only"], "runtime-arguments"),
        ("init", False, "runtime-arguments"),
        ("overrideCommand", False, "process-control"),
        ("appPort", [8080], "published-ports"),
        ("initializeCommand", "true", "host-lifecycle"),
        ("onCreateCommand", "true", "lifecycle-create"),
        ("updateContentCommand", "true", "lifecycle-create"),
        ("postStartCommand", "true", "lifecycle-start"),
        ("postAttachCommand", "true", "lifecycle-attach"),
        ("containerUser", "vscode", "user-selection"),
        ("remoteUser", "vscode", "user-selection"),
        ("updateRemoteUserUID", False, "user-selection"),
        ("userEnvProbe", "loginShell", "user-selection"),
        ("shutdownAction", "stopContainer", "lifecycle-control"),
        ("waitFor", "postCreateCommand", "lifecycle-control"),
        ("portsAttributes", {"8080": {"label": "web"}}, "port-attributes"),
        ("otherPortsAttributes", {"onAutoForward": "silent"}, "port-attributes"),
        ("capDrop", ["ALL"], "security-policy"),
        ("securityOpt", ["no-new-privileges"], "security-policy"),
    ],
)
def test_every_recognized_behavior_has_a_field_attribution(
    tmp_path: Path, field: str, value: object, capability: str
) -> None:
    module = load("devcontainer_config_source_" + field.lower())
    project = tmp_path / field
    project.mkdir()
    write_config(project, json.dumps({"image": IMAGE, field: value}))

    profile = module.normalize(project)

    assert field in profile["requirement_sources"][capability]


def test_build_only_configuration_is_deferred_to_backend_matching(
    tmp_path: Path,
) -> None:
    module = load("devcontainer_config_build_only")
    project = tmp_path / "build-only"
    project.mkdir()
    write_config(
        project,
        json.dumps({"name": "C++", "build": {"dockerfile": "Dockerfile"}}),
    )

    profile = module.normalize(project)

    assert profile["image"] is None
    assert profile["required_capabilities"] == ["image-build"]
    assert profile["requirement_sources"] == {"image-build": ["build"]}


def test_tagged_image_requires_a_resolving_native_engine(tmp_path: Path) -> None:
    module = load("devcontainer_config_tagged_image")
    project = tmp_path / "tagged"
    project.mkdir()
    path = write_config(project, json.dumps({"image": "ubuntu:24.04"}))

    profile = module.normalize(project)

    assert profile["image"] == "ubuntu:24.04"
    assert profile["required_capabilities"] == ["image-tag"]
    assert profile["fingerprint"] == module.configuration_fingerprint(
        project, path, json.loads(path.read_text(encoding="utf-8"))
    )


def test_build_fingerprint_includes_local_dockerfile(tmp_path: Path) -> None:
    module = load("devcontainer_config_dockerfile_fingerprint")
    project = tmp_path / "build"
    project.mkdir()
    config = write_config(
        project,
        json.dumps({"build": {"dockerfile": "Dockerfile"}}),
    )
    dockerfile = config.parent / "Dockerfile"
    dockerfile.write_text("FROM ubuntu:24.04\n", encoding="utf-8")
    before = module.normalize(project)["fingerprint"]

    dockerfile.write_text("FROM ubuntu:24.04\nRUN true\n", encoding="utf-8")

    assert module.normalize(project)["fingerprint"] != before


def test_host_requirement_failure_is_explicit(tmp_path: Path) -> None:
    encoded = base64.urlsafe_b64encode(
        json.dumps({"cpus": 1_000_000}).encode("utf-8")
    ).decode("ascii")

    result = run_command(
        [sys.executable, TOOL, "--check-host", encoded, "--workspace", tmp_path],
        cwd=tmp_path,
        check=False,
    )

    assert result.returncode == 2
    assert "host requirements are not satisfied" in result.stdout


def test_configuration_cannot_escape_project(tmp_path: Path) -> None:
    module = load("devcontainer_config_escape")
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps({"image": IMAGE}), encoding="utf-8")

    with pytest.raises(module.DevContainerError, match="inside the project"):
        module.normalize(project, "../outside.json")


def test_detailed_gpu_requirement_fails_until_it_can_be_validated(
    tmp_path: Path,
) -> None:
    module = load("devcontainer_config_detailed_gpu")
    project = tmp_path / "project"
    project.mkdir()
    write_config(
        project,
        json.dumps(
            {
                "image": IMAGE,
                "hostRequirements": {"gpu": {"cores": 1, "memory": "4gb"}},
            }
        ),
    )

    with pytest.raises(module.DevContainerError, match="cannot yet be validated"):
        module.normalize(project)


def test_nonlocal_forward_port_fails_closed(tmp_path: Path) -> None:
    module = load("devcontainer_config_nonlocal_port")
    project = tmp_path / "project"
    project.mkdir()
    write_config(
        project,
        json.dumps({"image": IMAGE, "forwardPorts": ["db.internal:5432"]}),
    )

    with pytest.raises(module.DevContainerError, match="only integer ports"):
        module.normalize(project)


def test_unknown_process_field_fails_closed(tmp_path: Path) -> None:
    module = load("devcontainer_config_unknown_field")
    project = tmp_path / "project"
    project.mkdir()
    write_config(
        project,
        json.dumps({"image": IMAGE, "futurePrivilegedRuntimeField": True}),
    )

    with pytest.raises(module.DevContainerError, match="unsupported Dev Container field"):
        module.normalize(project)


def test_required_gpu_needs_explicit_cdi_device(tmp_path: Path) -> None:
    module = load("devcontainer_config_gpu_without_cdi")
    project = tmp_path / "project"
    project.mkdir()
    write_config(
        project,
        json.dumps({"image": IMAGE, "hostRequirements": {"gpu": True}}),
    )

    with pytest.raises(module.DevContainerError, match="explicit CDI device"):
        module.normalize(project)


def test_gpu_probe_does_not_treat_an_unusable_client_as_hardware(
    tmp_path: Path, monkeypatch,
) -> None:
    module = load("devcontainer_config_gpu_probe")
    monkeypatch.setattr(module.shutil, "which", lambda name: "/usr/bin/nvidia-smi")
    monkeypatch.setattr(module, "DRI_DIRECTORY", tmp_path / "missing-dri")
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, b""),
    )

    assert module.gpu_available() is False
