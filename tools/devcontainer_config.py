#!/usr/bin/env python3
"""Parse Cloudmake's portable, least-privileged Dev Container profile."""

from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any


IMAGE = re.compile(r"^[^\s@]+@sha256:[0-9a-f]{64}$")
ENVIRONMENT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
CDI_DEVICE = re.compile(
    r"^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?/[A-Za-z0-9_.-]+=[A-Za-z0-9_.-]+$"
)
SIZE = re.compile(r"^(\d+)([tgmk]b)?$")
SIZE_MULTIPLIER = {
    None: 1,
    "kb": 1000,
    "mb": 1000**2,
    "gb": 1000**3,
    "tb": 1000**4,
}
DRI_DIRECTORY = Path("/dev/dri")


class DevContainerError(ValueError):
    """The selected Dev Container cannot be represented safely."""


def strip_json_comments(source: str) -> str:
    """Remove JSONC comments without changing quoted strings."""
    result: list[str] = []
    index = 0
    quoted = False
    escaped = False
    while index < len(source):
        character = source[index]
        if quoted:
            result.append(character)
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                quoted = False
            index += 1
            continue
        if character == '"':
            quoted = True
            result.append(character)
            index += 1
            continue
        if source.startswith("//", index):
            newline = source.find("\n", index + 2)
            if newline < 0:
                break
            result.append("\n")
            index = newline + 1
            continue
        if source.startswith("/*", index):
            end = source.find("*/", index + 2)
            if end < 0:
                raise DevContainerError("unterminated JSONC block comment")
            result.extend("\n" for value in source[index : end + 2] if value == "\n")
            index = end + 2
            continue
        result.append(character)
        index += 1
    if quoted:
        # json.loads supplies the useful syntax location.
        return "".join(result)
    return "".join(result)


def load_jsonc(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(strip_json_comments(path.read_text(encoding="utf-8")))
    except OSError as error:
        raise DevContainerError(f"cannot read {path}: {error}") from error
    except json.JSONDecodeError as error:
        raise DevContainerError(f"invalid Dev Container JSON in {path}: {error}") from error
    if not isinstance(payload, dict):
        raise DevContainerError("Dev Container configuration must be a JSON object")
    return payload


def resolve_path(project: Path, selected: str) -> Path:
    project = project.resolve()
    candidates = (
        [project / selected]
        if selected
        else [project / ".devcontainer" / "devcontainer.json", project / ".devcontainer.json"]
    )
    existing = next((candidate for candidate in candidates if candidate.is_file()), None)
    if existing is None:
        names = ", ".join(os.fspath(path.relative_to(project)) for path in candidates)
        raise DevContainerError(f"Dev Container configuration was not found: {names}")
    resolved = existing.resolve()
    try:
        resolved.relative_to(project)
    except ValueError as error:
        raise DevContainerError("Dev Container configuration must remain inside the project") from error
    return resolved


def literal_environment(value: Any, field: str) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise DevContainerError(f"{field} must be an object")
    result: dict[str, str] = {}
    for name, item in value.items():
        if not isinstance(name, str) or ENVIRONMENT_NAME.fullmatch(name) is None:
            raise DevContainerError(f"{field} contains invalid environment name {name!r}")
        if not isinstance(item, str) or "\0" in item or "\n" in item:
            raise DevContainerError(f"{field}.{name} must be a single-line string")
        if "${" in item:
            raise DevContainerError(
                f"{field}.{name} uses interpolation; Cloudmake does not import host secrets"
            )
        result[name] = item
    return result


def parse_size(value: Any, field: str) -> int:
    if not isinstance(value, str):
        raise DevContainerError(f"hostRequirements.{field} must be a size string")
    match = SIZE.fullmatch(value.lower())
    if match is None:
        raise DevContainerError(
            f"hostRequirements.{field} must use bytes, kb, mb, gb, or tb"
        )
    return int(match.group(1)) * SIZE_MULTIPLIER[match.group(2)]


def host_requirements(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise DevContainerError("hostRequirements must be an object")
    unknown = set(value) - {"cpus", "memory", "storage", "gpu"}
    if unknown:
        raise DevContainerError(
            "unsupported hostRequirements field(s): " + ", ".join(sorted(unknown))
        )
    result: dict[str, Any] = {}
    cpus = value.get("cpus")
    if cpus is not None:
        if isinstance(cpus, bool) or not isinstance(cpus, int) or cpus < 1:
            raise DevContainerError("hostRequirements.cpus must be a positive integer")
        result["cpus"] = cpus
    for field in ("memory", "storage"):
        if field in value:
            result[field] = parse_size(value[field], field)
    gpu = value.get("gpu")
    if gpu is not None:
        if gpu in (True, False, "optional"):
            result["gpu"] = gpu
        elif isinstance(gpu, dict):
            raise DevContainerError(
                "detailed hostRequirements.gpu cores/memory cannot yet be "
                "validated portably; use true or optional"
            )
        else:
            raise DevContainerError(
                "hostRequirements.gpu must be true, false, optional, or an object"
            )
    return result


def forward_ports(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise DevContainerError("forwardPorts must be an array")
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for item in value:
        host = "127.0.0.1"
        if isinstance(item, bool):
            raise DevContainerError(f"invalid forwardPorts entry {item!r}")
        if isinstance(item, int):
            port = item
        elif isinstance(item, str) and ":" in item:
            host, port_text = item.rsplit(":", 1)
            if not port_text.isdigit():
                raise DevContainerError(f"invalid forwardPorts entry {item!r}")
            if host != "localhost":
                raise DevContainerError(
                    "portable Cloudmake forwardPorts supports only integer ports "
                    "or localhost:PORT"
                )
            host = "127.0.0.1"
            port = int(port_text)
        else:
            raise DevContainerError(f"invalid forwardPorts entry {item!r}")
        if port < 1 or port > 65535:
            raise DevContainerError(f"forwardPorts port is outside 1..65535: {port}")
        key = (host, port)
        if key in seen:
            raise DevContainerError(f"duplicate forwardPorts entry {item!r}")
        seen.add(key)
        result.append({"host": host, "port": port})
    return result


def normalize(project: Path, selected: str = "") -> dict[str, Any]:
    path = resolve_path(project, selected)
    payload = load_jsonc(path)
    image = payload.get("image")
    if not isinstance(image, str) or IMAGE.fullmatch(image) is None:
        raise DevContainerError(
            "the portable Cloudmake profile requires image=REF@sha256:<64 lowercase hex digits>"
        )

    forbidden_nonempty = {
        "build", "dockerFile", "dockerComposeFile", "service", "runServices",
        "features", "overrideFeatureInstallOrder", "secrets", "mounts", "runArgs",
        "appPort", "workspaceMount", "initializeCommand", "onCreateCommand",
        "updateContentCommand", "postCreateCommand", "postStartCommand",
        "postAttachCommand", "containerUser", "remoteUser", "shutdownAction",
        "userEnvProbe", "waitFor", "portsAttributes", "otherPortsAttributes",
        "init", "capDrop", "updateRemoteUserUID",
    }
    known = forbidden_nonempty | {
        "$schema", "name", "image", "containerEnv", "remoteEnv",
        "hostRequirements", "forwardPorts", "workspaceFolder", "securityOpt",
        "privileged", "capAdd", "customizations",
    }
    unknown = set(payload) - known
    if unknown:
        raise DevContainerError(
            "unsupported Dev Container field(s): " + ", ".join(sorted(unknown))
        )
    unsupported = [name for name in forbidden_nonempty if payload.get(name) not in (None, [], {}, "")]
    if unsupported:
        raise DevContainerError(
            "portable Cloudmake Dev Containers do not support: "
            + ", ".join(sorted(unsupported))
        )
    if payload.get("privileged") not in (None, False):
        raise DevContainerError("privileged Dev Containers violate the least-privilege profile")
    if payload.get("capAdd") not in (None, []):
        raise DevContainerError("capAdd is not supported by the least-privilege profile")
    security = payload.get("securityOpt")
    if security not in (None, [], ["no-new-privileges"], ["no-new-privileges=true"]):
        raise DevContainerError("securityOpt may only request no-new-privileges")
    if payload.get("workspaceFolder") not in (None, "/workspace"):
        raise DevContainerError("portable Cloudmake Dev Containers use /workspace")

    environment = literal_environment(payload.get("containerEnv"), "containerEnv")
    environment.update(literal_environment(payload.get("remoteEnv"), "remoteEnv"))
    customizations = payload.get("customizations", {})
    if not isinstance(customizations, dict):
        raise DevContainerError("customizations must be an object")
    cloudmake = customizations.get("cloudmake", {})
    if not isinstance(cloudmake, dict):
        raise DevContainerError("customizations.cloudmake must be an object")
    unknown_custom = set(cloudmake) - {"devices"}
    if unknown_custom:
        raise DevContainerError(
            "unsupported customizations.cloudmake field(s): "
            + ", ".join(sorted(unknown_custom))
        )
    devices = cloudmake.get("devices", [])
    if not isinstance(devices, list) or not all(isinstance(item, str) for item in devices):
        raise DevContainerError("customizations.cloudmake.devices must be a string array")
    invalid_devices = [item for item in devices if CDI_DEVICE.fullmatch(item) is None]
    if invalid_devices:
        raise DevContainerError("invalid CDI device(s): " + ", ".join(invalid_devices))
    if len(devices) != len(set(devices)):
        raise DevContainerError("customizations.cloudmake.devices contains duplicates")
    requirements = host_requirements(payload.get("hostRequirements"))
    if requirements.get("gpu") is True and not devices:
        raise DevContainerError(
            "hostRequirements.gpu=true requires an explicit CDI device in "
            "customizations.cloudmake.devices"
        )

    return {
        "schema": 1,
        "path": path.relative_to(project.resolve()).as_posix(),
        "image": image,
        "environment": [f"{name}={value}" for name, value in sorted(environment.items())],
        "host_requirements": requirements,
        "forward_ports": forward_ports(payload.get("forwardPorts")),
        "devices": devices,
    }


def decode_object(value: str, description: str) -> dict[str, Any]:
    try:
        payload = json.loads(base64.urlsafe_b64decode(value.encode("ascii")).decode("utf-8"))
    except Exception as error:
        raise DevContainerError(f"invalid encoded {description}") from error
    if not isinstance(payload, dict):
        raise DevContainerError(f"encoded {description} must be an object")
    return payload


def available_memory() -> int:
    total = int(os.sysconf("SC_PAGE_SIZE")) * int(os.sysconf("SC_PHYS_PAGES"))
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemTotal:"):
                total = int(line.split()[1]) * 1024
                break
    except (OSError, ValueError, IndexError):
        pass
    limits: list[int] = [total]
    for path in (Path("/sys/fs/cgroup/memory.max"), Path("/sys/fs/cgroup/memory/memory.limit_in_bytes")):
        try:
            value = path.read_text(encoding="utf-8").strip()
            if value != "max":
                limits.append(int(value))
        except (OSError, ValueError):
            pass
    return min(limits)


def gpu_available() -> bool:
    nvidia_smi = shutil.which("nvidia-smi")
    if nvidia_smi is not None:
        try:
            completed = subprocess.run(
                [nvidia_smi, "-L"],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
            if completed.returncode == 0 and completed.stdout.strip():
                return True
        except (OSError, subprocess.SubprocessError):
            pass
    try:
        return any(
            path.name.startswith(("card", "renderD"))
            for path in DRI_DIRECTORY.iterdir()
        )
    except OSError:
        return False


def check_host(requirements: dict[str, Any], workspace: Path) -> dict[str, Any]:
    observed = {
        "cpus": (
            len(os.sched_getaffinity(0))
            if hasattr(os, "sched_getaffinity")
            else os.cpu_count() or 1
        ),
        "memory": available_memory(),
        "storage": shutil.disk_usage(workspace).free,
        "gpu": gpu_available(),
    }
    failures: list[str] = []
    for field in ("cpus", "memory", "storage"):
        required = requirements.get(field)
        if isinstance(required, int) and observed[field] < required:
            failures.append(f"{field} requires {required}, observed {observed[field]}")
    gpu = requirements.get("gpu")
    if (gpu is True or isinstance(gpu, dict)) and not observed["gpu"]:
        failures.append("gpu is required but no GPU device was observed")
    if failures:
        raise DevContainerError("host requirements are not satisfied: " + "; ".join(failures))
    return observed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path)
    parser.add_argument("--config", default="")
    parser.add_argument("--check-host", default="")
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    arguments = parser.parse_args()
    try:
        if arguments.check_host:
            observed = check_host(
                decode_object(arguments.check_host, "host requirements"),
                arguments.workspace,
            )
            print(json.dumps(observed, sort_keys=True))
        else:
            if arguments.project is None:
                parser.error("--project is required")
            print(json.dumps(normalize(arguments.project, arguments.config), sort_keys=True))
    except DevContainerError as error:
        print(f"cloudmake: Dev Container compatibility failure: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
