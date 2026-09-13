#!/usr/bin/env python3
"""Run one Make target in a persistent, provider-native Dev Container."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any
import uuid


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return value if isinstance(value, dict) else {}


def run_stream(
    command: list[str], *, cwd: Path, hidden_lines: set[str] | None = None
) -> tuple[int, list[str]]:
    process = subprocess.Popen(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
    )
    lines: list[str] = []
    assert process.stdout is not None
    try:
        for line in process.stdout:
            lines.append(line)
            if line.rstrip("\r\n") not in (hidden_lines or set()):
                print(line, end="", flush=True)
        return process.wait(), lines
    except KeyboardInterrupt:
        process.send_signal(2)
        process.wait()
        raise


def final_object(lines: list[str]) -> dict[str, Any]:
    for line in reversed(lines):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return {}


def repository_digests(docker: str, reference: str) -> list[str]:
    inspected = subprocess.run(
        [docker, "image", "inspect", "--format", "{{json .RepoDigests}}", reference],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if inspected.returncode:
        return []
    try:
        values = json.loads(inspected.stdout)
    except json.JSONDecodeError:
        return []
    return sorted(str(value) for value in values) if isinstance(values, list) else []


def repository_name(reference: str) -> str:
    name = reference.split("@", 1)[0]
    slash = name.rfind("/")
    colon = name.rfind(":")
    return name[:colon] if colon > slash else name


def remove_managed_container(
    docker: str, container: str, project_key: str
) -> tuple[bool, str]:
    if not container or container.startswith("-"):
        return False, "stored native Dev Container identity is invalid"
    label = subprocess.run(
        [
            docker, "inspect", "--format",
            '{{ index .Config.Labels "cloudmake.project" }}', container,
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if label.returncode:
        # A successful list operation with no exact stored ID is positive
        # absence. This makes an interrupted remove -> receipt transition
        # recoverable without treating an unavailable daemon as absence.
        present = subprocess.run(
            [
                docker, "ps", "-a", "--no-trunc", "--filter", f"id={container}",
                "--format", "{{.ID}}",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if present.returncode == 0 and not present.stdout.strip():
            return True, ""
        return False, "stored native Dev Container ownership could not be verified"
    if label.stdout.strip() != project_key:
        return False, "stored container is not positively owned by this Cloudmake project"
    removed = subprocess.run(
        [docker, "rm", "-f", container],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if removed.returncode:
        detail = (removed.stderr or removed.stdout).strip()
        return False, f"managed Dev Container removal failed: {detail or 'unknown error'}"
    return True, ""


def inspect_image(docker: str, container: str, source_image: str) -> dict[str, Any]:
    inspected = subprocess.run(
        [docker, "inspect", "--format", "{{.Image}}", container],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    image_id = inspected.stdout.strip() if inspected.returncode == 0 else ""
    result: dict[str, Any] = {"container_id": container}
    if "@sha256:" in source_image:
        result["resolved_digest"] = source_image
    elif source_image:
        source_digests = repository_digests(docker, source_image)
        if source_digests:
            repository = repository_name(source_image)
            matching = [value for value in source_digests if value.split("@", 1)[0] == repository]
            result["resolved_digest"] = (matching or source_digests)[0]
    if image_id:
        result["image_id"] = image_id
        if "resolved_digest" not in result:
            image_digests = repository_digests(docker, image_id)
            if image_digests:
                result["resolved_digest"] = image_digests[0]
        platform = subprocess.run(
            [docker, "image", "inspect", "--format", "{{.Os}}/{{.Architecture}}", image_id],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if platform.returncode == 0 and "/" in platform.stdout.strip():
            result["platform"] = platform.stdout.strip()
    return result


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--project", required=True, type=Path)
    result.add_argument("--config", required=True)
    result.add_argument("--project-key", required=True)
    result.add_argument("--fingerprint", required=True)
    result.add_argument("--source-image", default="")
    result.add_argument("--target", required=True)
    result.add_argument("--assignment", action="append", default=[])
    result.add_argument("--jobs", default="4")
    result.add_argument("--state", required=True, type=Path)
    result.add_argument("--result", required=True, type=Path)
    return result


def main(argv: list[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    project = arguments.project.resolve()
    config = (project / arguments.config).resolve()
    receipt = load_json(arguments.state)
    output: dict[str, Any] = {
        "schema": 1,
        "runtime": "devcontainer-cli",
        "status": "preparation-failed",
        "source_fingerprint": arguments.fingerprint,
        "target_submission": "not_submitted",
        "retry_safe": True,
    }
    devcontainer = shutil.which("devcontainer")
    docker = shutil.which("docker")
    if devcontainer is None or docker is None:
        missing = "devcontainer" if devcontainer is None else "docker"
        output["error"] = f"required native Dev Container command was not found: {missing}"
        atomic_json(arguments.result, output)
        print(f"[cloudmake] {output['error']}", file=sys.stderr)
        return 2

    project_label = f"cloudmake.project={arguments.project_key}"
    configuration_label = f"cloudmake.config={arguments.fingerprint}"
    # A missing receipt is not proof that a matching container is safe to
    # reuse. The stable label is Cloudmake-owned, so reconstruct it unless a
    # receipt positively binds it to this configuration fingerprint.
    changed = (
        receipt.get("fingerprint") != arguments.fingerprint
        or receipt.get("engine_contract") != 2
    )
    if receipt and changed:
        owned, error = remove_managed_container(
            docker, str(receipt.get("container_id", "")), arguments.project_key
        )
        if not owned:
            output["error"] = error
            atomic_json(arguments.result, output)
            print(f"[cloudmake] {error}", file=sys.stderr)
            return 1
        # Bind any subsequent recovery to the new identity before preparation
        # can execute lifecycle hooks. The reference CLI's stable labels and
        # internal lifecycle markers then recover the same construction.
        atomic_json(
            arguments.state,
            {
                "schema": 1,
                "engine_contract": 2,
                "fingerprint": arguments.fingerprint,
                "status": "preparing",
            },
        )
    up = [
        devcontainer, "up", "--workspace-folder", os.fspath(project),
        "--mount-workspace-git-root", "false",
        "--config", os.fspath(config),
        "--id-label", project_label, "--id-label", configuration_label,
        "--skip-post-attach",
    ]
    code, lines = run_stream(up, cwd=project)
    prepared = final_object(lines)
    if code != 0 or prepared.get("outcome") != "success":
        output["error"] = prepared.get("message", "native Dev Container preparation failed")
        atomic_json(arguments.result, output)
        return code or 1
    container = prepared.get("containerId")
    if not isinstance(container, str) or not container:
        output["error"] = "native Dev Container engine did not report a container ID"
        atomic_json(arguments.result, output)
        return 1

    image = inspect_image(docker, container, arguments.source_image)
    if not image.get("image_id"):
        output.update(error="native Dev Container image identity could not be inspected", **image)
        atomic_json(arguments.result, output)
        print(f"[cloudmake] {output['error']}", file=sys.stderr)
        return 1
    if (
        arguments.source_image
        and "@sha256:" not in arguments.source_image
        and not image.get("resolved_digest")
    ):
        output.update(error="tagged Dev Container image did not resolve to a registry digest", **image)
        atomic_json(arguments.result, output)
        print(f"[cloudmake] {output['error']}", file=sys.stderr)
        return 1
    workstation = {
        "schema": 1,
        "engine_contract": 2,
        "fingerprint": arguments.fingerprint,
        "container_id": container,
        "status": "ready",
        **image,
    }
    atomic_json(arguments.state, workstation)
    if receipt and changed:
        preparation = "rebuilt"
    elif receipt.get("container_id") == container:
        preparation = "reused"
    elif receipt:
        preparation = "reconstructed"
    else:
        preparation = "started"
    common_exec = [
        devcontainer, "exec", "--workspace-folder", os.fspath(project),
        "--mount-workspace-git-root", "false",
        "--config", os.fspath(config), "--container-id", container,
    ]
    preflight = subprocess.run(
        [*common_exec, "sh", "-c", "command -v make >/dev/null"],
        cwd=project,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if preflight.returncode:
        if preflight.stdout:
            print(preflight.stdout, end="" if preflight.stdout.endswith("\n") else "\n")
        output.update(
            error="native Dev Container Make preflight failed",
            preparation=preparation,
            **image,
        )
        atomic_json(arguments.result, output)
        return preflight.returncode
    output.update(
        status="running",
        preparation=preparation,
        target_submission="submitted",
        retry_safe=False,
        **image,
    )
    marker = f"cloudmake-target-submitted-{uuid.uuid4().hex}"
    command = [
        *common_exec,
        "sh", "-c", 'printf "%s\\n" "$1"; shift; exec "$@"',
        "cloudmake", marker, "make", "-f", "Makefile", "-j", arguments.jobs,
        arguments.target, *arguments.assignment,
    ]
    code, lines = run_stream(command, cwd=project, hidden_lines={marker})
    submitted = any(line.rstrip("\r\n") == marker for line in lines)
    effective_code = code if submitted else code or 1
    if not submitted:
        print(
            "[cloudmake] native Dev Container execution ended without target "
            "submission confirmation",
            file=sys.stderr,
        )
    output.update(
        status=(
            "succeeded" if code == 0 and submitted
            else "target-failed" if submitted
            else "execution-ambiguous"
        ),
        exit_code=effective_code,
        process_exit_code=code,
        target_submission="confirmed" if submitted else "ambiguous",
    )
    atomic_json(arguments.result, output)
    return effective_code


if __name__ == "__main__":
    raise SystemExit(main())
