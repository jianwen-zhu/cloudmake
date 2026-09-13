#!/usr/bin/env python3
"""Reconcile a Codespace's provider-native OCI development environment."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import subprocess
import sys
import tempfile
import time
from typing import Any


SCHEMA = 1
ADAPTER_REVISION = 1
IMAGE_PATTERN = re.compile(r"^[^\s@]+@sha256:[0-9a-f]{64}$")
TRANSIENT_SSH_ERRORS = (
    "connection reset by peer",
    "context deadline exceeded",
    "deadlineexceeded",
    "failed to invoke ssh rpc",
    "timed out while waiting for the codespace to start",
)


class EnvironmentError(RuntimeError):
    """The provider environment could not be reconciled safely."""


def decode_image(value: str) -> str:
    try:
        image = base64.urlsafe_b64decode(value.encode("ascii")).decode("utf-8")
    except Exception as error:
        raise EnvironmentError("invalid encoded OCI image reference") from error
    if IMAGE_PATTERN.fullmatch(image) is None:
        raise EnvironmentError("invalid immutable OCI image reference")
    return image


def decode_json(value: str, description: str) -> Any:
    try:
        return json.loads(base64.urlsafe_b64decode(value.encode("ascii")).decode("utf-8"))
    except Exception as error:
        raise EnvironmentError(f"invalid encoded {description}") from error


def run(
    command: list[str], *, input_text: str | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=False,
        text=True,
        input=input_text,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def gh_ssh(
    gh: str, codespace: str, script: str, *, input_text: str | None = None
) -> subprocess.CompletedProcess[str]:
    # gh treats the post-`--` command as one remote shell string. Supplying
    # `sh`, `-c`, and the program as separate argv entries loses the program's
    # quoting when gh reconstructs that string.
    remote_command = shlex.join(["sh", "-c", script])
    command = [gh, "codespace", "ssh", "-c", codespace, "--", remote_command]
    delays = (2, 5, 10)
    for attempt in range(1, len(delays) + 2):
        completed = run(command, input_text=input_text)
        if completed.returncode == 0:
            return completed
        detail = (completed.stderr or completed.stdout).lower()
        if not any(pattern in detail for pattern in TRANSIENT_SSH_ERRORS):
            return completed
        if attempt > len(delays):
            return completed
        delay = delays[attempt - 1]
        print(
            "[cloudmake] Codespaces SSH temporarily unavailable; "
            f"retrying preparation in {delay}s "
            f"(attempt {attempt + 1}/{len(delays) + 1})",
            file=sys.stderr,
        )
        time.sleep(delay)
    raise AssertionError("unreachable")


def checked(completed: subprocess.CompletedProcess[str], description: str) -> str:
    if completed.returncode:
        detail = (completed.stderr or completed.stdout).strip()
        suffix = f": {detail}" if detail else ""
        raise EnvironmentError(f"{description} failed{suffix}")
    return completed.stdout


def workspace_root(gh: str, codespace: str) -> PurePosixPath:
    # `gh codespace ssh` starts in the remote user's home directory, not in
    # the repository mounted by Codespaces. Discover the dedicated anchor
    # from the provider-persistent /workspaces tree instead. Requiring one
    # top-level Git checkout avoids silently rebuilding the wrong repository
    # when a Codespace has been repurposed as a multi-repository workspace.
    script = (
        "for path in /workspaces/*; do "
        "test -d \"$path\" || continue; "
        "test -e \"$path/.git\" || continue; "
        "printf '%s\\n' \"$path\"; "
        "done"
    )
    output = checked(
        gh_ssh(gh, codespace, script),
        "Codespaces workspace discovery",
    )
    candidates = [line for line in output.splitlines() if line]
    if not candidates:
        raise EnvironmentError(
            "Codespaces anchor repository under /workspaces was not found"
        )
    if len(candidates) != 1:
        raise EnvironmentError(
            "Codespaces anchor repository under /workspaces is ambiguous"
        )
    path = PurePosixPath(candidates[0])
    if not path.is_absolute() or len(path.parts) < 3 or path.parts[1] != "workspaces":
        raise EnvironmentError(
            f"Codespaces workspace is outside /workspaces: {candidates[0]!r}"
        )
    return path


def marker_path(root: PurePosixPath) -> PurePosixPath:
    return root.parent / ".cloudmake" / "native-oci-environment.json"


def read_marker(gh: str, codespace: str, path: PurePosixPath) -> dict[str, Any]:
    quoted = shlex.quote(path.as_posix())
    completed = gh_ssh(
        gh,
        codespace,
        f"if test -f {quoted}; then cat {quoted}; fi",
    )
    payload = checked(completed, "Codespaces environment inspection").strip()
    if not payload:
        return {}
    try:
        marker: Any = json.loads(payload)
    except json.JSONDecodeError as error:
        raise EnvironmentError("Codespaces environment marker is invalid") from error
    if not isinstance(marker, dict) or marker.get("schema") != SCHEMA:
        raise EnvironmentError("Codespaces environment marker has an unknown schema")
    return marker


def write_remote(
    gh: str,
    codespace: str,
    path: PurePosixPath,
    content: str,
) -> None:
    parent = shlex.quote(path.parent.as_posix())
    destination = shlex.quote(path.as_posix())
    temporary = shlex.quote(f"{path}.cloudmake-tmp")
    script = (
        f"umask 077; mkdir -p {parent}; cat > {temporary}; "
        f"mv {temporary} {destination}"
    )
    checked(
        gh_ssh(gh, codespace, script, input_text=content),
        f"Codespaces environment write for {path.name}",
    )


def remove_remote(gh: str, codespace: str, path: PurePosixPath) -> None:
    checked(
        gh_ssh(gh, codespace, f"rm -f {shlex.quote(path.as_posix())}"),
        "Codespaces environment marker removal",
    )


def generated_files(
    image: str,
    environment: list[str] | None = None,
    host_requirements: dict[str, Any] | None = None,
    forward_ports: list[dict[str, Any]] | None = None,
) -> tuple[str, str]:
    dockerfile = f"""FROM {image}
USER root
RUN set -eu; \\
    missing=0; \\
    for command in make rsync tar python3; do command -v \"$command\" >/dev/null 2>&1 || missing=1; done; \\
    if [ \"$missing\" = 1 ]; then \\
      command -v apt-get >/dev/null 2>&1 || {{ echo 'cloudmake: native Codespaces OCI images must provide make, rsync, tar, and python3 or apt-get' >&2; exit 2; }}; \\
      apt-get update; \\
      DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends make rsync tar python3; \\
      rm -rf /var/lib/apt/lists/*; \\
    fi
"""
    configuration = {
        "name": "Cloudmake native OCI environment",
        "build": {"dockerfile": "cloudmake-oci.Dockerfile"},
        "features": {
            "ghcr.io/devcontainers/features/common-utils:2.5.9": {
                "configureZshAsDefaultShell": False,
                "installOhMyZsh": False,
                "installOhMyZshConfig": False,
                "installZsh": False,
                "upgradePackages": False,
                "username": "vscode",
            },
            "ghcr.io/devcontainers/features/sshd:1.1.0": {},
        },
        "remoteUser": "vscode",
    }
    if environment:
        configuration["remoteEnv"] = {
            value.split("=", 1)[0]: value.split("=", 1)[1]
            for value in environment
        }
    if host_requirements:
        converted = dict(host_requirements)
        for field in ("memory", "storage"):
            if field in converted:
                converted[field] = str(converted[field])
        gpu = converted.get("gpu")
        if isinstance(gpu, dict) and "memory" in gpu:
            converted["gpu"] = {**gpu, "memory": str(gpu["memory"])}
        configuration["hostRequirements"] = converted
    if forward_ports:
        configuration["forwardPorts"] = [
            item["port"]
            if item["host"] == "127.0.0.1"
            else f"{item['host']}:{item['port']}"
            for item in forward_ports
        ]
    return dockerfile, json.dumps(configuration, indent=2, sort_keys=True) + "\n"


def configuration_digest(dockerfile: str, configuration: str) -> str:
    return hashlib.sha256(
        dockerfile.encode("utf-8") + b"\0" + configuration.encode("utf-8")
    ).hexdigest()


def rebuild(gh: str, codespace: str) -> None:
    print("[cloudmake] Codespaces OCI environment changed; rebuilding resource")
    environment = os.environ.copy()
    environment["GH_PROMPT_DISABLED"] = "1"
    completed = subprocess.run(
        [gh, "codespace", "rebuild", "-c", codespace],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
    )
    checked(completed, "Codespaces rebuild")


def wait_for_ssh(gh: str, codespace: str, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    last = ""
    while True:
        completed = gh_ssh(gh, codespace, "true")
        if completed.returncode == 0:
            return
        last = (completed.stderr or completed.stdout).strip()
        if time.monotonic() >= deadline:
            suffix = f": {last}" if last else ""
            raise EnvironmentError(
                f"Codespaces did not become reachable after rebuild{suffix}"
            )
        time.sleep(5)


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def reconcile(arguments: argparse.Namespace) -> dict[str, Any]:
    root = workspace_root(arguments.gh, arguments.codespace)
    marker = marker_path(root)
    current = read_marker(arguments.gh, arguments.codespace, marker)
    if arguments.mode == "native":
        if not current:
            return {"schema": SCHEMA, "mode": "native", "outcome": "reused"}
        write_remote(
            arguments.gh,
            arguments.codespace,
            root / ".devcontainer" / "devcontainer.json",
            arguments.native_config.read_text(encoding="utf-8"),
        )
        write_remote(
            arguments.gh,
            arguments.codespace,
            root / ".devcontainer" / "Dockerfile",
            arguments.native_dockerfile.read_text(encoding="utf-8"),
        )
        rebuild(arguments.gh, arguments.codespace)
        wait_for_ssh(arguments.gh, arguments.codespace, arguments.timeout)
        remove_remote(arguments.gh, arguments.codespace, marker)
        return {"schema": SCHEMA, "mode": "native", "outcome": "rebuilt"}

    image = decode_image(arguments.image_b64)
    environment = decode_json(
        getattr(arguments, "environment_b64", "W10="),
        "Dev Container environment",
    )
    host_requirements = decode_json(
        getattr(arguments, "host_requirements_b64", "e30="),
        "Dev Container host requirements",
    )
    forward_ports = decode_json(
        getattr(arguments, "forward_ports_b64", "W10="),
        "Dev Container ports",
    )
    if not isinstance(environment, list) or not all(
        isinstance(value, str) and "=" in value for value in environment
    ):
        raise EnvironmentError("invalid Dev Container environment")
    if not isinstance(host_requirements, dict) or not isinstance(forward_ports, list):
        raise EnvironmentError("invalid Dev Container requirements or ports")
    dockerfile, configuration = generated_files(
        image, environment, host_requirements, forward_ports
    )
    digest = configuration_digest(dockerfile, configuration)
    profile_metadata = {
        "environment_names": sorted(value.split("=", 1)[0] for value in environment),
        "host_requirements": host_requirements,
        "forward_ports": forward_ports,
    }
    if (
        current.get("status") == "ready"
        and current.get("image") == image
        and current.get("adapter_revision") == ADAPTER_REVISION
        and current.get("configuration_digest") == digest
    ):
        return {
            "schema": SCHEMA,
            "mode": "oci",
            "image": image,
            "runtime": "provider-native",
            "outcome": "reused",
            **profile_metadata,
        }
    write_remote(
        arguments.gh,
        arguments.codespace,
        root / ".devcontainer" / "cloudmake-oci.Dockerfile",
        dockerfile,
    )
    write_remote(
        arguments.gh,
        arguments.codespace,
        root / ".devcontainer" / "devcontainer.json",
        configuration,
    )
    # Record intent before the provider rebuild. If the rebuild or this client
    # dies, the next invocation must not mistake the workstation for the
    # neutral anchor. `--native` can recover it, while selecting this image
    # safely retries preparation.
    preparing_marker = {
        "schema": SCHEMA,
        "status": "preparing",
        "adapter_revision": ADAPTER_REVISION,
        "image": image,
        "configuration_digest": digest,
        **profile_metadata,
    }
    write_remote(
        arguments.gh,
        arguments.codespace,
        marker,
        json.dumps(preparing_marker, indent=2, sort_keys=True) + "\n",
    )
    rebuild(arguments.gh, arguments.codespace)
    wait_for_ssh(arguments.gh, arguments.codespace, arguments.timeout)
    remote_marker = {
        "schema": SCHEMA,
        "status": "ready",
        "adapter_revision": ADAPTER_REVISION,
        "image": image,
        "configuration_digest": digest,
        **profile_metadata,
    }
    write_remote(
        arguments.gh,
        arguments.codespace,
        marker,
        json.dumps(remote_marker, indent=2, sort_keys=True) + "\n",
    )
    return {
        "schema": SCHEMA,
        "mode": "oci",
        "image": image,
        "runtime": "provider-native",
        "outcome": "rebuilt",
        **profile_metadata,
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--gh", default="gh")
    result.add_argument("--codespace", required=True)
    result.add_argument("--mode", choices=("native", "oci"), required=True)
    result.add_argument("--image-b64", default="")
    result.add_argument("--environment-b64", default="W10=")
    result.add_argument("--host-requirements-b64", default="e30=")
    result.add_argument("--forward-ports-b64", default="W10=")
    result.add_argument("--native-config", type=Path, required=True)
    result.add_argument("--native-dockerfile", type=Path, required=True)
    result.add_argument("--receipt", type=Path, required=True)
    result.add_argument("--timeout", type=float, default=300)
    return result


def main() -> int:
    arguments = parser().parse_args()
    arguments.receipt.unlink(missing_ok=True)
    try:
        receipt = reconcile(arguments)
        atomic_json(arguments.receipt, receipt)
    except (EnvironmentError, OSError) as error:
        print(f"cloudmake: Codespaces environment preparation failed: {error}", file=sys.stderr)
        return 70
    if receipt["mode"] == "oci":
        digest = str(receipt["image"]).rsplit("@", 1)[1]
        print(
            "[cloudmake] oci-environment=provider-native "
            f"image={digest} state={receipt['outcome']}"
        )
    elif receipt["outcome"] == "rebuilt":
        print("[cloudmake] oci-environment=native state=restored")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
