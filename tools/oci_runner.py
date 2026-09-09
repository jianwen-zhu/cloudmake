#!/usr/bin/env python3
"""Validate and execute one project Make target through an OCI image."""

from __future__ import annotations

import argparse
import base64
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import posixpath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import Any, Iterator


IMAGE = re.compile(r"^([^\s@]+)@sha256:([0-9a-f]{64})$")
CDI_DEVICE = re.compile(
    r"^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?/[A-Za-z0-9_.-]+=[A-Za-z0-9_.-]+$"
)
RUNTIMES = ("auto", "podman", "docker", "nerdctl", "proot", "crun")
HIGH_LEVEL_RUNTIMES = ("podman", "docker", "nerdctl")
CDI_RUNTIMES = (*HIGH_LEVEL_RUNTIMES, "proot", "crun")
STANDARD_DEVICES = ("null", "zero", "full", "random", "urandom")
CDI_DIRECTORIES = (Path("/etc/cdi"), Path("/var/run/cdi"))
EX_SOFTWARE = getattr(os, "EX_SOFTWARE", 70)


class RunnerError(RuntimeError):
    """An expected image, compatibility, or runner failure before Make."""


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def image_reference(value: str) -> tuple[str, str]:
    match = IMAGE.fullmatch(value)
    if match is None:
        raise RunnerError(
            "OCI images must be immutable references of the form "
            "REGISTRY/IMAGE@sha256:<64 lowercase hex digits>"
        )
    return match.group(1), f"sha256:{match.group(2)}"


def device_name(value: str) -> str:
    if CDI_DEVICE.fullmatch(value) is None:
        raise RunnerError(
            f"invalid CDI device {value!r}; expected vendor.example/class=device"
        )
    return value


def relative_makefile(value: str) -> str:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or "\n" in value:
        raise RunnerError("project Makefile must be a safe relative path")
    return path.as_posix()


def decode_value(value: str, description: str) -> str:
    try:
        decoded = base64.b64decode(
            value.encode("ascii"), altchars=b"-_", validate=True
        ).decode("utf-8")
    except Exception as error:
        raise RunnerError(f"invalid encoded {description}") from error
    return decoded


def decode_arguments(value: str) -> list[str]:
    try:
        decoded = json.loads(decode_value(value, "project arguments"))
    except json.JSONDecodeError as error:
        raise RunnerError("invalid encoded project arguments") from error
    if not isinstance(decoded, list) or not all(isinstance(item, str) for item in decoded):
        raise RunnerError("project arguments must be a JSON string list")
    return decoded


def normalized_architecture(value: str) -> str:
    return {"x86_64": "amd64", "aarch64": "arm64"}.get(value, value)


def run_checked(
    command: list[str], *, capture: bool = False, description: str,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        check=False,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )
    if result.returncode:
        detail = ""
        if capture:
            detail = (result.stderr or result.stdout or "").strip()
        suffix = f": {detail}" if detail else ""
        raise RunnerError(f"{description} failed with exit status {result.returncode}{suffix}")
    return result


def runtime_readiness(candidate: str) -> tuple[bool, str]:
    if candidate == "proot":
        required = ("skopeo", "umoci", "proot", "setpriv")
    elif candidate == "crun":
        if os.geteuid() != 0:
            return False, "requires a root managed-VM adapter"
        required = ("skopeo", "umoci", "crun")
    else:
        required = (candidate,)
    missing = [name for name in required if shutil.which(name) is None]
    if missing:
        return False, "missing " + ", ".join(missing)
    if candidate not in (*HIGH_LEVEL_RUNTIMES, "crun"):
        return True, "ready"
    try:
        probe = [candidate, "--version"] if candidate == "crun" else [candidate, "info"]
        completed = subprocess.run(
            probe,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return False, str(error)
    if completed.returncode:
        detail = (completed.stdout or "").strip().splitlines()
        return False, detail[-1] if detail else f"status {completed.returncode}"
    return True, "ready"


def select_runtime(
    requested: str, candidates: list[str] | None = None, *, requires_cdi: bool = False
) -> str:
    declared = candidates or [*HIGH_LEVEL_RUNTIMES, "proot"]
    if len(declared) != len(set(declared)):
        raise RunnerError("OCI runtime candidate list contains duplicates")
    invalid = [candidate for candidate in declared if candidate not in RUNTIMES[1:]]
    if invalid:
        raise RunnerError("invalid OCI runtime candidate(s): " + ", ".join(invalid))
    choices = [requested] if requested != "auto" else declared
    if requires_cdi:
        choices = [candidate for candidate in choices if candidate in CDI_RUNTIMES]
        if not choices:
            raise RunnerError(
                "no backend-declared OCI runtime option can apply CDI devices"
            )
    if requested != "auto" and candidates and requested not in declared:
        raise RunnerError(
            f"OCI runtime {requested!r} is not declared by the selected backend"
        )
    failures: list[str] = []
    for candidate in choices:
        ready, detail = runtime_readiness(candidate)
        if ready:
            return candidate
        failures.append(f"{candidate}: {detail}")
    raise RunnerError(
        "no declared OCI runtime option is ready; " + "; ".join(failures)
    )


def inspect_with_skopeo(reference: str, digest: str) -> dict[str, Any]:
    executable = shutil.which("skopeo")
    if executable is None:
        return {"requested_digest": digest}
    result = run_checked(
        [executable, "inspect", f"docker://{reference}"],
        capture=True,
        description="OCI registry inspection",
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise RunnerError("OCI registry inspection returned invalid JSON") from error
    observed_digest = payload.get("Digest")
    if observed_digest != digest:
        raise RunnerError(
            f"OCI digest mismatch: requested {digest}, registry reported {observed_digest!r}"
        )
    image_os = payload.get("Os")
    architecture = payload.get("Architecture")
    if image_os and image_os != "linux":
        raise RunnerError(f"OCI image requires unsupported operating system {image_os!r}")
    host_architecture = normalized_architecture(platform.machine())
    return {
        "requested_digest": digest,
        "registry_digest": observed_digest,
        "os": image_os,
        "architecture": architecture,
        "host_architecture": host_architecture,
        "architecture_match": (
            architecture == host_architecture if architecture else None
        ),
    }


def inspect_with_runtime(runtime: str, reference: str, digest: str) -> dict[str, Any]:
    """Inspect the locally pulled image when skopeo is not installed.

    Pulling an immutable reference already asks the runtime to verify the
    requested manifest digest.  The local inspection adds an explicit record
    of the selected platform and, where exposed, the repository digest.
    """
    result = run_checked(
        [runtime, "image", "inspect", reference],
        capture=True,
        description=f"{runtime} image inspection",
    )
    try:
        payload = json.loads(result.stdout)
        if isinstance(payload, list):
            payload = payload[0]
        if not isinstance(payload, dict):
            raise ValueError
    except (json.JSONDecodeError, IndexError, ValueError) as error:
        raise RunnerError(f"{runtime} image inspection returned invalid JSON") from error

    observed: set[str] = set()
    for value in payload.get("RepoDigests", payload.get("RepoDigest", [])) or []:
        if isinstance(value, str) and "@" in value:
            observed.add(value.rsplit("@", 1)[1])
    direct_digest = payload.get("Digest")
    if isinstance(direct_digest, str) and direct_digest.startswith("sha256:"):
        observed.add(direct_digest)
    if observed and digest not in observed:
        raise RunnerError(
            f"OCI digest mismatch: requested {digest}, runtime reported "
            + ", ".join(sorted(observed))
        )

    image_os = payload.get("Os", payload.get("OS"))
    architecture = payload.get("Architecture")
    if image_os and image_os != "linux":
        raise RunnerError(f"OCI image requires unsupported operating system {image_os!r}")
    host_architecture = normalized_architecture(platform.machine())
    return {
        "requested_digest": digest,
        "runtime_digests": sorted(observed),
        "os": image_os,
        "architecture": architecture,
        "host_architecture": host_architecture,
        "architecture_match": (
            architecture == host_architecture if architecture else None
        ),
    }


@contextlib.contextmanager
def cache_lock(cache: Path) -> Iterator[None]:
    cache.mkdir(parents=True, exist_ok=True)
    lock = cache / ".lock"
    with lock.open("a+", encoding="utf-8") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        yield


def materialize_bundle(
    *, reference: str, digest: str, cache_root: Path
) -> tuple[Path, dict[str, Any]]:
    image_cache = cache_root / "images" / digest.removeprefix("sha256:")
    bundle = image_cache / "bundle"
    layout = image_cache / "layout"
    receipt = image_cache / "receipt.json"
    with cache_lock(image_cache):
        saved: dict[str, Any] = {}
        if receipt.is_file():
            try:
                saved = json.loads(receipt.read_text(encoding="utf-8"))
            except Exception:
                saved = {}

        cache_matches = (
            saved.get("reference") == reference
            and saved.get("digest") == digest
            and (layout / "oci-layout").is_file()
            and (layout / "index.json").is_file()
        )
        if cache_matches:
            if (bundle / "rootfs").is_dir():
                bundle.chmod(0o755)
                return bundle, saved.get("image", {"requested_digest": digest})

            staging = Path(tempfile.mkdtemp(prefix=".unpack-", dir=image_cache))
            unpacked = staging / "bundle"
            try:
                run_checked(
                    [
                        "umoci", "unpack", "--rootless", "--image",
                        f"{layout}:cloudmake", str(unpacked),
                    ],
                    description="OCI image materialization",
                )
                if bundle.is_symlink() or bundle.is_file():
                    bundle.unlink()
                elif bundle.exists():
                    shutil.rmtree(bundle)
                os.replace(unpacked, bundle)
                bundle.chmod(0o755)
            finally:
                shutil.rmtree(staging, ignore_errors=True)
            return bundle, saved.get("image", {"requested_digest": digest})

        image = inspect_with_skopeo(reference, digest)
        staging = Path(tempfile.mkdtemp(prefix=".image-", dir=image_cache))
        staged_layout = staging / "layout"
        unpacked = staging / "bundle"
        try:
            run_checked(
                [
                    "skopeo", "copy", f"docker://{reference}",
                    f"oci:{staged_layout}:cloudmake",
                ],
                description="OCI image pull",
            )
            run_checked(
                [
                    "umoci", "unpack", "--rootless", "--image",
                    f"{staged_layout}:cloudmake", str(unpacked),
                ],
                description="OCI image materialization",
            )
            if layout.is_symlink() or layout.is_file():
                layout.unlink()
            elif layout.exists():
                shutil.rmtree(layout)
            if bundle.is_symlink() or bundle.is_file():
                bundle.unlink()
            elif bundle.exists():
                shutil.rmtree(bundle)
            os.replace(staged_layout, layout)
            os.replace(unpacked, bundle)
            # umoci creates the bundle beneath a 0700 staging directory. The
            # selected adapter may run the image process as an unprivileged user.
            bundle.chmod(0o755)
            atomic_json(
                receipt,
                {
                    "schema": 1,
                    "reference": reference,
                    "digest": digest,
                    "image": image,
                },
            )
        finally:
            shutil.rmtree(staging, ignore_errors=True)
    return bundle, image


def native_base_command(
    runtime: str, source: Path, reference: str, devices: list[str]
) -> list[str]:
    command = [
        runtime,
        "run",
        "--rm",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges=true",
        "--tmpfs",
        "/tmp:rw,nosuid,nodev",
        "--workdir",
        "/workspace",
    ]
    if runtime == "podman":
        command.extend(["--userns=keep-id"])
    command.extend(["--user", f"{os.getuid()}:{os.getgid()}"])
    command.extend(["--volume", f"{source}:/workspace:rw"])
    for device in devices:
        command.extend(["--device", device])
    command.extend(["--entrypoint", "make", reference])
    return command


def oci_process_environment(bundle: Path) -> list[str]:
    config = bundle / "config.json"
    try:
        payload = json.loads(config.read_text(encoding="utf-8"))
        values = payload.get("process", {}).get("env", [])
    except (OSError, json.JSONDecodeError, AttributeError) as error:
        raise RunnerError("materialized OCI bundle has no valid runtime configuration") from error
    if not isinstance(values, list):
        raise RunnerError("materialized OCI bundle has an invalid process environment")
    environment: dict[str, str] = {}
    for value in values:
        if not isinstance(value, str) or "=" not in value or "\0" in value:
            raise RunnerError("materialized OCI bundle has an invalid environment entry")
        name, item = value.split("=", 1)
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            raise RunnerError("materialized OCI bundle has an invalid environment name")
        environment[name] = item
    environment.setdefault(
        "PATH", "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
    )
    environment.setdefault("HOME", "/tmp")
    return [f"{name}={value}" for name, value in sorted(environment.items())]


def absolute_container_path(value: Any, description: str) -> str:
    if not isinstance(value, str) or "\0" in value:
        raise RunnerError(f"CDI {description} must be an absolute path")
    path = PurePosixPath(value)
    if not path.is_absolute() or ".." in path.parts:
        raise RunnerError(f"CDI {description} must be an absolute path")
    return path.as_posix()


def cdi_specifications(directories: list[Path]) -> dict[str, tuple[dict[str, Any], Path]]:
    """Load the strict JSON subset consumed by direct managed-VM adapters.

    Higher-level runtimes remain responsible for their own CDI implementation.
    Each direct adapter fails closed on fields it cannot faithfully translate.
    """
    resolved: dict[str, tuple[dict[str, Any], Path]] = {}
    yaml_present = False
    for directory in directories:
        if not directory.is_dir():
            continue
        yaml_present = yaml_present or any(directory.glob("*.yaml")) or any(
            directory.glob("*.yml")
        )
        for path in sorted(directory.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise RunnerError(f"invalid CDI JSON specification {path}: {error}") from error
            if not isinstance(payload, dict):
                raise RunnerError(f"invalid CDI JSON specification {path}: expected an object")
            unknown = set(payload) - {
                "cdiVersion", "kind", "annotations", "containerEdits", "devices"
            }
            if unknown:
                raise RunnerError(
                    f"unsupported CDI specification field(s) in {path}: "
                    + ", ".join(sorted(unknown))
                )
            version, kind, devices = (
                payload.get("cdiVersion"), payload.get("kind"), payload.get("devices")
            )
            if not isinstance(version, str) or re.fullmatch(r"(?:0\.[3-9]|1\.[01])\.\d+", version) is None:
                raise RunnerError(f"unsupported CDI version in {path}: {version!r}")
            if not isinstance(kind, str) or "/" not in kind:
                raise RunnerError(f"invalid CDI kind in {path}")
            if not isinstance(devices, list) or not devices:
                raise RunnerError(f"invalid CDI devices in {path}")
            common = payload.get("containerEdits", {})
            if not isinstance(common, dict):
                raise RunnerError(f"invalid CDI containerEdits in {path}")
            seen: set[str] = set()
            for entry in devices:
                if not isinstance(entry, dict) or set(entry) - {
                    "name", "annotations", "containerEdits"
                }:
                    raise RunnerError(f"invalid CDI device entry in {path}")
                name = entry.get("name")
                edits = entry.get("containerEdits", {})
                if not isinstance(name, str) or not isinstance(edits, dict):
                    raise RunnerError(f"invalid CDI device entry in {path}")
                qualified = f"{kind}={name}"
                if CDI_DEVICE.fullmatch(qualified) is None or qualified in seen:
                    raise RunnerError(f"invalid or duplicate CDI device {qualified!r} in {path}")
                seen.add(qualified)
                combined: dict[str, Any] = {}
                for source in (common, edits):
                    for key, value in source.items():
                        if value in (None, [], {}):
                            continue
                        if key not in {"env", "deviceNodes", "mounts"}:
                            raise RunnerError(
                                f"CDI field {key!r} used by {qualified!r} is unsupported "
                                "by Cloudmake's direct OCI adapter profile"
                            )
                        if not isinstance(value, list):
                            raise RunnerError(f"CDI field {key!r} for {qualified!r} must be a list")
                        combined.setdefault(key, []).extend(value)
                # Later CDI directories intentionally override earlier ones,
                # matching the standard /var/run/cdi precedence convention.
                resolved[qualified] = (combined, path)
    if not resolved and yaml_present:
        raise RunnerError(
            "Cloudmake's direct OCI adapters require JSON CDI specifications; "
            "a YAML-only CDI installation was found"
        )
    return resolved


def apply_cdi_edits(
    payload: dict[str, Any], devices: list[str], directories: list[Path]
) -> list[str]:
    if not devices:
        return []
    specifications = cdi_specifications(directories)
    missing = [device for device in devices if device not in specifications]
    if missing:
        raise RunnerError("CDI device specification not found: " + ", ".join(missing))
    process = payload.setdefault("process", {})
    environment: dict[str, str] = {}
    for value in process.get("env", []):
        if isinstance(value, str) and "=" in value:
            name, item = value.split("=", 1)
            environment[name] = item
    mounts = payload.setdefault("mounts", [])
    destinations = {
        item.get("destination") for item in mounts if isinstance(item, dict)
    }
    sources: list[str] = []
    for device in devices:
        edits, path = specifications[device]
        sources.append(os.fspath(path))
        for value in edits.get("env", []):
            if not isinstance(value, str) or "=" not in value or "\0" in value:
                raise RunnerError(f"CDI environment entry for {device!r} is invalid")
            name, item = value.split("=", 1)
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) is None:
                raise RunnerError(f"CDI environment name for {device!r} is invalid")
            environment[name] = item
        for item in edits.get("mounts", []):
            if not isinstance(item, dict) or set(item) - {
                "hostPath", "containerPath", "type", "options"
            }:
                raise RunnerError(f"CDI mount for {device!r} is invalid")
            source = absolute_container_path(item.get("hostPath"), "hostPath")
            destination = absolute_container_path(
                item.get("containerPath"), "containerPath"
            )
            mount_type = item.get("type", "bind")
            options = item.get("options", [])
            if mount_type != "bind" or not isinstance(options, list) or not all(
                isinstance(option, str) for option in options
            ):
                raise RunnerError(
                    f"CDI mount {destination!r} for {device!r} is not a bind mount"
                )
            if not Path(source).exists():
                raise RunnerError(f"CDI host mount source is unavailable: {source}")
            if destination in destinations:
                raise RunnerError(f"duplicate OCI/CDI mount destination: {destination}")
            normalized_options = list(options)
            if not {"bind", "rbind"}.intersection(normalized_options):
                normalized_options.insert(0, "rbind" if Path(source).is_dir() else "bind")
            mounts.append(
                {
                    "destination": destination,
                    "type": "bind",
                    "source": source,
                    "options": normalized_options,
                }
            )
            destinations.add(destination)
        for item in edits.get("deviceNodes", []):
            if not isinstance(item, dict) or set(item) - {
                "path", "hostPath", "type", "major", "minor", "fileMode",
                "permissions", "uid", "gid"
            }:
                raise RunnerError(f"CDI device node for {device!r} is invalid")
            unsupported = [
                name for name in ("type", "major", "minor", "fileMode", "permissions", "uid", "gid")
                if item.get(name) is not None
            ]
            if unsupported:
                raise RunnerError(
                    f"CDI device node overrides for {device!r} are unsupported: "
                    + ", ".join(unsupported)
                )
            destination = absolute_container_path(item.get("path"), "device path")
            source = absolute_container_path(
                item.get("hostPath", destination), "device hostPath"
            )
            try:
                mode = Path(source).stat().st_mode
            except OSError as error:
                raise RunnerError(f"CDI host device is unavailable: {source}") from error
            if not (stat.S_ISCHR(mode) or stat.S_ISBLK(mode)):
                raise RunnerError(f"CDI host device is not a device node: {source}")
            if destination in destinations:
                raise RunnerError(f"duplicate OCI/CDI mount destination: {destination}")
            mounts.append(
                {
                    "destination": destination,
                    "type": "bind",
                    "source": source,
                    "options": ["bind"],
                }
            )
            destinations.add(destination)
    process["env"] = [f"{name}={value}" for name, value in sorted(environment.items())]
    return sources


def workspace_owner(value: str) -> tuple[int, int]:
    try:
        uid_text, gid_text = value.split(":", 1)
        uid, gid = int(uid_text), int(gid_text)
    except (ValueError, AttributeError) as error:
        raise RunnerError("restricted OCI execution requires a numeric UID:GID owner") from error
    if uid <= 0 or gid <= 0:
        raise RunnerError("restricted OCI execution requires a non-root UID:GID owner")
    return uid, gid


def chown_workspace(source: Path, uid: int, gid: int) -> None:
    for directory, names, files in os.walk(source, topdown=False, followlinks=False):
        root = Path(directory)
        for name in (*files, *names):
            path = root / name
            info = path.lstat()
            if (info.st_uid, info.st_gid) != (uid, gid):
                os.chown(path, uid, gid, follow_symlinks=False)
        info = root.lstat()
        if (info.st_uid, info.st_gid) != (uid, gid):
            os.chown(root, uid, gid, follow_symlinks=False)


def proot_guest_link_repairs(
    image_home: Path, rootfs: Path
) -> list[tuple[str, str, str]]:
    """Find checkpointed links that PRoot must recreate in its guest namespace.

    PRoot may encode an absolute guest link with the current host rootfs path.
    That path expires with the VM.  CloudMake derives the original guest target
    only when it exists in the same digest-pinned rootfs; arbitrary absolute
    project links remain untouched.
    """
    links: dict[str, str] = {}
    repairs: dict[str, tuple[str, str, str]] = {}
    current_rootfs = rootfs.resolve()
    digest = rootfs.parent.parent.name
    old_rootfs = re.compile(
        rf"^.*/cache/oci/images/{re.escape(digest)}/bundle/rootfs(?:/(.*))?$"
    )
    for directory, directory_names, file_names in os.walk(
        image_home, topdown=True, followlinks=False
    ):
        root = Path(directory)
        for name in [*directory_names, *file_names]:
            path = root / name
            if not path.is_symlink():
                continue
            target = os.readlink(path)
            guest_link = "/home/cloudmake/" + path.relative_to(image_home).as_posix()
            links[guest_link] = target
            if not target.startswith(os.sep):
                continue
            match = old_rootfs.fullmatch(target)
            if match is not None:
                suffix = PurePosixPath(match.group(1) or "")
            else:
                candidate = Path(target)
                try:
                    suffix = PurePosixPath(
                        candidate.relative_to(current_rootfs).as_posix()
                    )
                except ValueError:
                    suffix = PurePosixPath(target).relative_to("/")
            if ".." in suffix.parts:
                continue
            image_target = current_rootfs.joinpath(*suffix.parts)
            if not image_target.is_file():
                continue
            guest_target = "/" + suffix.as_posix()
            repairs[guest_link] = (
                os.fspath(image_target), guest_target, guest_link
            )

    # Recreate only the relative-link closure leading to a validated image
    # target. This avoids touching unrelated project links while repairing the
    # complete venv-style python -> python3 -> python3.X chain.
    changed = True
    while changed:
        changed = False
        for guest_link, target in links.items():
            if guest_link in repairs or target.startswith(os.sep):
                continue
            guest_target = posixpath.normpath(
                posixpath.join(posixpath.dirname(guest_link), target)
            )
            if posixpath.dirname(guest_target) != posixpath.dirname(guest_link):
                continue
            if guest_target not in repairs:
                continue
            repairs[guest_link] = ("", target, guest_link)
            changed = True
    return sorted(repairs.values(), key=lambda item: item[2])


def proot_identity_prefix(source: Path, owner: str | None) -> tuple[list[str], str]:
    setpriv = shutil.which("setpriv")
    if setpriv is None:
        raise RunnerError("PRoot execution requires setpriv to enforce noNewPrivileges")
    if os.geteuid() != 0:
        if owner is not None:
            raise RunnerError("a PRoot workspace owner may be supplied only by a root VM adapter")
        return [setpriv, "--no-new-privs"], f"{os.getuid()}:{os.getgid()}"
    if owner is None:
        raise RunnerError(
            "PRoot cannot safely translate an OCI root while running as root; "
            "the backend must select an unprivileged workspace owner"
        )
    uid, gid = workspace_owner(owner)
    chown_workspace(source, uid, gid)
    return [
        setpriv,
        "--no-new-privs",
        "--inh-caps=-all",
        "--ambient-caps=-all",
        "--bounding-set=-all",
        f"--reuid={uid}",
        f"--regid={gid}",
        "--clear-groups",
    ], owner


def proot_base_command(
    bundle: Path,
    source: Path,
    identity_prefix: list[str] | None = None,
    cdi_bindings: list[tuple[str, str]] | None = None,
    environment: list[str] | None = None,
    runtime_tmp: Path | None = None,
    runtime_home: Path | None = None,
) -> list[str]:
    command = [
        *(identity_prefix or []),
        "proot",
        "-r",
        str(bundle / "rootfs"),
        "-b",
        f"{source}:/workspace",
    ]
    if runtime_tmp is not None:
        command.extend(["-b", f"{runtime_tmp}:/tmp"])
    if runtime_home is not None:
        command.extend(["-b", f"{runtime_home}:/home/cloudmake"])
    # OCI Linux processes expect the kernel API filesystems supplied by a
    # conventional runtime.  PRoot's minimal -r form does not add them; omit
    # them and device libraries can be present while CUDA initialization still
    # fails because /proc/driver and /sys/module are invisible.
    for kernel_api in (Path("/proc"), Path("/sys")):
        if kernel_api.is_dir():
            command.extend(["-b", f"{kernel_api}:{kernel_api}"])
    for name in STANDARD_DEVICES:
        device = Path("/dev") / name
        if device.is_char_device() or device.is_block_device():
            command.extend(["-b", f"{device}:/dev/{name}"])
    for name in ("resolv.conf", "hosts"):
        configuration = Path("/etc") / name
        if configuration.exists():
            command.extend(["-b", f"{configuration.resolve()}:/etc/{name}"])
    for host, container in cdi_bindings or []:
        command.extend(["-b", f"{host}:{container}"])
    command.extend([
        "-w",
        "/workspace",
        "/usr/bin/env",
        "-i",
        *(environment or oci_process_environment(bundle)),
        "make",
    ])
    return command


def proot_cdi_configuration(
    bundle: Path, devices: list[str], directories: list[Path]
) -> tuple[list[tuple[str, str]], list[str], list[str]]:
    payload: dict[str, Any] = {
        "process": {"env": oci_process_environment(bundle)},
        "mounts": [],
    }
    sources = apply_cdi_edits(payload, devices, directories)
    bindings = [
        (str(item["source"]), str(item["destination"]))
        for item in payload["mounts"]
    ]
    return bindings, list(payload["process"]["env"]), sources


def prepare_proot_binding_targets(
    rootfs: Path, bindings: list[tuple[str, str]]
) -> None:
    """Materialize safe guest mount points required by PRoot bind emulation."""
    resolved_root = rootfs.resolve()
    for source_text, destination_text in bindings:
        source = Path(source_text)
        destination = PurePosixPath(destination_text)
        current = rootfs
        for part in destination.parts[1:-1]:
            current /= part
            if current.is_symlink():
                resolved_parent = current.resolve(strict=False)
                try:
                    resolved_parent.relative_to(resolved_root)
                except ValueError as error:
                    raise RunnerError(
                        f"OCI/CDI mount parent escapes the image root: {destination_text}"
                    ) from error
                current = resolved_parent
            current.mkdir(mode=0o755, exist_ok=True)
            if not current.is_dir():
                raise RunnerError(
                    f"OCI/CDI mount parent is not a directory: {destination_text}"
                )
        target = current / destination.name
        if target.is_symlink():
            raise RunnerError(
                f"OCI/CDI mount target must not be a symbolic link: {destination_text}"
            )
        if source.is_dir():
            target.mkdir(mode=0o755, exist_ok=True)
            if not target.is_dir():
                raise RunnerError(
                    f"OCI/CDI directory mount target is not a directory: {destination_text}"
                )
        elif not target.exists():
            target.touch(mode=0o644)
        elif not target.is_file():
            raise RunnerError(
                f"OCI/CDI file mount target is not a file: {destination_text}"
            )


def safe_runtime_directory(rootfs: Path, name: str) -> Path:
    path = rootfs / name
    if path.is_symlink():
        raise RunnerError(f"OCI image {name!r} runtime path must not be a symbolic link")
    path.mkdir(mode=0o755, exist_ok=True)
    if not path.is_dir():
        raise RunnerError(f"OCI image {name!r} runtime path is not a directory")
    return path


def crun_base_command(
    bundle: Path,
    source: Path,
    owner: str,
    internal_result: Path,
    devices: list[str],
    cdi_directories: list[Path],
) -> list[str]:
    command = [
        sys.executable,
        os.fspath(Path(__file__).resolve()),
        "--internal-crun-exec",
        os.fspath(bundle),
        os.fspath(source),
        owner,
        os.fspath(internal_result),
    ]
    for directory in cdi_directories:
        command.extend(["--cdi-dir", os.fspath(directory)])
    for device in devices:
        command.extend(["--device", device])
    command.extend(["--", "make"])
    return command


def internal_crun_parser(arguments: list[str]) -> argparse.Namespace:
    try:
        separator = arguments.index("--")
    except ValueError as error:
        raise RunnerError("invalid internal crun invocation") from error
    result = argparse.ArgumentParser(add_help=False)
    result.add_argument("bundle", type=Path)
    result.add_argument("source", type=Path)
    result.add_argument("owner")
    result.add_argument("result", type=Path)
    result.add_argument("--cdi-dir", action="append", type=Path, default=[])
    result.add_argument("--device", action="append", default=[])
    parsed = result.parse_args(arguments[:separator])
    parsed.command = arguments[separator + 1 :]
    if not parsed.command:
        raise RunnerError("invalid internal crun invocation")
    return parsed


def internal_crun_exec(arguments: list[str]) -> int:
    parsed = internal_crun_parser(arguments)
    bundle = parsed.bundle.resolve()
    source = parsed.source.resolve()
    internal_result = parsed.result.resolve()
    rootfs = bundle / "rootfs"
    uid, gid = workspace_owner(parsed.owner)
    internal_result.unlink(missing_ok=True)
    container_id = f"cloudmake-{os.getpid()}"
    try:
        with cache_lock(bundle):
            if not rootfs.is_dir() or not source.is_dir():
                raise RunnerError("crun OCI root or project workspace is unavailable")
            safe_runtime_directory(rootfs, "workspace")
            safe_runtime_directory(rootfs, "tmp")
            safe_runtime_directory(rootfs, "run")
            chown_workspace(source, uid, gid)
            try:
                payload = json.loads((bundle / "config.json").read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise RunnerError("materialized OCI bundle has no valid runtime configuration") from error
            if not isinstance(payload, dict):
                raise RunnerError("materialized OCI runtime configuration is not an object")
            for field in ("root", "process", "linux"):
                value = payload.get(field, {})
                if not isinstance(value, dict):
                    raise RunnerError(
                        f"materialized OCI runtime configuration has invalid {field!r}"
                    )

            with tempfile.TemporaryDirectory(prefix=".crun-", dir=bundle.parent) as temporary:
                runtime_bundle = Path(temporary)
                runtime_tmp = runtime_bundle / "tmp"
                runtime_receipt = runtime_bundle / "receipt"
                runtime_tmp.mkdir(mode=0o777)
                runtime_tmp.chmod(0o1777)
                runtime_receipt.mkdir(mode=0o777)
                runtime_receipt.chmod(0o777)

                payload.setdefault("root", {})["path"] = os.fspath(rootfs)
                payload["root"]["readonly"] = True
                process = payload.setdefault("process", {})
                process.update(
                    terminal=False,
                    cwd="/workspace",
                    user={"uid": uid, "gid": gid},
                    noNewPrivileges=True,
                )
                process["capabilities"] = {
                    name: []
                    for name in (
                        "bounding", "effective", "inheritable", "permitted", "ambient"
                    )
                }
                process["env"] = oci_process_environment(bundle)
                process["args"] = [
                    "/bin/sh",
                    "-c",
                    '"$@"; code=$?; printf \'{"schema":1,"exit_code":%s}\\n\' "$code" '
                    '> /run/cloudmake/result.json; exit "$code"',
                    "cloudmake",
                    *parsed.command,
                ]

                linux = payload.setdefault("linux", {})
                linux.pop("resources", None)
                linux.pop("cgroupsPath", None)
                # The outer managed VM remains the security boundary. Colab
                # does not permit a fresh procfs or writable cgroup hierarchy.
                linux.pop("seccomp", None)
                namespaces = [
                    item for item in linux.get("namespaces", [])
                    if isinstance(item, dict)
                    and item.get("type")
                    not in {"cgroup", "network", "pid", "user"}
                ]
                if not any(item.get("type") == "mount" for item in namespaces):
                    namespaces.append({"type": "mount"})
                linux["namespaces"] = namespaces

                mounts: list[dict[str, Any]] = [
                    {
                        "destination": "/proc", "type": "bind", "source": "/proc",
                        "options": ["rbind", "rw", "nosuid", "nodev", "noexec"],
                    },
                    {
                        "destination": "/sys", "type": "bind", "source": "/sys",
                        "options": ["rbind", "ro", "nosuid", "nodev", "noexec"],
                    },
                    {
                        "destination": "/workspace", "type": "bind",
                        "source": os.fspath(source),
                        "options": ["rbind", "rw", "nosuid", "nodev"],
                    },
                    {
                        "destination": "/tmp", "type": "bind",
                        "source": os.fspath(runtime_tmp),
                        "options": ["rbind", "rw", "nosuid", "nodev"],
                    },
                    {
                        "destination": "/run/cloudmake", "type": "bind",
                        "source": os.fspath(runtime_receipt),
                        "options": ["rbind", "rw", "nosuid", "nodev", "noexec"],
                    },
                ]
                for name in STANDARD_DEVICES:
                    host = Path("/dev") / name
                    if host.exists():
                        mounts.append(
                            {
                                "destination": f"/dev/{name}", "type": "bind",
                                "source": os.fspath(host), "options": ["bind"],
                            }
                        )
                payload["mounts"] = mounts
                cdi_sources = apply_cdi_edits(
                    payload,
                    [device_name(value) for value in parsed.device],
                    [*CDI_DIRECTORIES, *parsed.cdi_dir],
                )
                (runtime_bundle / "config.json").write_text(
                    json.dumps(payload), encoding="utf-8"
                )
                completed = subprocess.run(
                    ["crun", "--cgroup-manager=disabled", "run", container_id],
                    check=False,
                    cwd=runtime_bundle,
                )
                private_result = runtime_receipt / "result.json"
                try:
                    private = json.loads(private_result.read_text(encoding="utf-8"))
                except Exception as error:
                    raise RunnerError(
                        f"crun did not produce a target receipt (status {completed.returncode})"
                    ) from error
                exit_code = private.get("exit_code")
                if private.get("schema") != 1 or not isinstance(exit_code, int):
                    raise RunnerError("crun produced an invalid target receipt")
                if exit_code != completed.returncode:
                    raise RunnerError("crun target receipt did not match process status")
        atomic_json(
            internal_result,
            {
                "schema": 1,
                "status": "completed",
                "exit_code": exit_code,
                "profile": "colab-host-integrated-no-cgroup",
                "cdi_specs": cdi_sources,
            },
        )
        return exit_code
    except (OSError, subprocess.SubprocessError) as error:
        failure = RunnerError(f"crun OCI execution failed: {error}")
        atomic_json(
            internal_result,
            {"schema": 1, "status": "infrastructure-failed", "error": str(failure)},
        )
        raise failure from error
    except RunnerError as error:
        atomic_json(
            internal_result,
            {"schema": 1, "status": "infrastructure-failed", "error": str(error)},
        )
        raise
    finally:
        try:
            subprocess.run(
                ["crun", "delete", "--force", container_id],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            pass


def prepare(
    *,
    runtime: str,
    reference: str,
    digest: str,
    source: Path,
    devices: list[str],
    cache: Path,
    internal_result: Path | None = None,
    rootless_workspace_owner: str | None = None,
    cdi_directories: list[Path] | None = None,
    runtime_tmp: Path | None = None,
    runtime_home: Path | None = None,
) -> tuple[list[str], dict[str, Any], str | None]:
    if not source.is_dir():
        raise RunnerError(f"project workspace is unavailable: {source}")
    if runtime == "proot":
        bundle, image = materialize_bundle(
            reference=reference, digest=digest, cache_root=cache
        )
        identity_prefix, identity = proot_identity_prefix(
            source, rootless_workspace_owner
        )
        link_repairs: list[tuple[str, str, str]] = []
        if runtime_home is not None:
            runtime_home.mkdir(parents=True, exist_ok=True)
            if rootless_workspace_owner is not None:
                uid, gid = workspace_owner(rootless_workspace_owner)
                chown_workspace(runtime_home, uid, gid)
            link_repairs = proot_guest_link_repairs(
                runtime_home, bundle / "rootfs"
            )
        bindings: list[tuple[str, str]] = []
        environment = oci_process_environment(bundle)
        if devices:
            device_bindings, environment, _ = proot_cdi_configuration(
                bundle, devices, cdi_directories or []
            )
            bindings.extend(device_bindings)
            prepare_proot_binding_targets(bundle / "rootfs", bindings)
        if runtime_home is not None:
            environment = [
                value for value in environment if not value.startswith("HOME=")
            ]
            environment.append("HOME=/home/cloudmake")
            environment.sort()
        repair_base = proot_base_command(
            bundle,
            source,
            identity_prefix,
            bindings,
            environment,
            runtime_tmp,
            runtime_home,
        )
        for _, guest_target, guest_link in link_repairs:
            run_checked(
                [*repair_base[:-1], "/bin/ln", "-snf", guest_target, guest_link],
                description="PRoot checkpoint link repair",
            )
        base = proot_base_command(
            bundle,
            source,
            identity_prefix,
            bindings,
            environment,
            runtime_tmp,
            runtime_home,
        )
        for _, _, guest_link in link_repairs:
            run_checked(
                [*base[:-1], "/usr/bin/test", "-x", guest_link],
                description="PRoot checkpoint link validation",
            )
        if link_repairs:
            repaired_paths = ",".join(item[2] for item in link_repairs)
            print(
                f"[cloudmake] PRoot rehydrated checkpointed-links={len(link_repairs)} "
                f"paths={repaired_paths}",
                flush=True,
            )
        return base, image, identity

    if runtime == "crun":
        if rootless_workspace_owner is None:
            raise RunnerError("the Colab crun profile requires a non-root workspace owner")
        if internal_result is None:
            raise RunnerError("the Colab crun profile requires an internal result path")
        identity = ":".join(
            str(value) for value in workspace_owner(rootless_workspace_owner)
        )
        bundle, image = materialize_bundle(
            reference=reference, digest=digest, cache_root=cache
        )
        return (
            crun_base_command(
                bundle,
                source,
                identity,
                internal_result,
                devices,
                cdi_directories or [],
            ),
            image,
            identity,
        )

    run_checked([runtime, "pull", reference], description=f"{runtime} image pull")
    # A native runtime has already pulled and verified the digest-pinned
    # reference. Inspect that exact local object through the selected runtime;
    # an unrelated host skopeo installation must not add a second registry
    # request or change otherwise identical behavior across machines.
    image = inspect_with_runtime(runtime, reference, digest)
    return native_base_command(runtime, source, reference, devices), image, None


def validate_internal_execution(path: Path, exit_code: int, runtime: str) -> None:
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except Exception as error:
        raise RunnerError(
            f"{runtime} execution did not produce a valid result receipt"
        ) from error
    if receipt.get("schema") != 1 or receipt.get("status") != "completed":
        detail = receipt.get("error", f"{runtime} execution did not complete")
        raise RunnerError(str(detail))
    if receipt.get("exit_code") != exit_code:
        raise RunnerError(f"{runtime} execution result did not match process status")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--mode", choices=("preflight", "run"), required=True)
    result.add_argument("--image", required=True)
    result.add_argument("--runtime", choices=RUNTIMES, default="auto")
    result.add_argument(
        "--runtime-candidate", choices=RUNTIMES[1:], action="append", default=[]
    )
    result.add_argument("--device", action="append", default=[])
    result.add_argument("--source", type=Path, required=True)
    result.add_argument("--cache", type=Path, required=True)
    result.add_argument("--makefile", default="Makefile")
    result.add_argument("--target-b64", default="")
    result.add_argument("--arguments-b64", default="W10=")
    result.add_argument("--jobs", type=int, default=1)
    result.add_argument("--rootless-workspace-owner")
    result.add_argument("--runtime-home", type=Path)
    result.add_argument("--cdi-spec-dir", action="append", type=Path, default=[])
    result.add_argument("--result", type=Path, required=True)
    return result


def main() -> int:
    if sys.argv[1:2] == ["--internal-crun-exec"]:
        try:
            return internal_crun_exec(sys.argv[2:])
        except RunnerError as error:
            print(f"[cloudmake] OCI infrastructure failure: {error}", file=sys.stderr)
            return EX_SOFTWARE
    arguments = parser().parse_args()
    receipt: dict[str, Any] = {"schema": 1, "mode": arguments.mode}
    runtime_tmp: Path | None = None
    try:
        _, digest = image_reference(arguments.image)
        devices = [device_name(value) for value in arguments.device]
        makefile = relative_makefile(arguments.makefile)
        if arguments.jobs < 1:
            raise RunnerError("parallel job count must be positive")
        runtime = select_runtime(
            arguments.runtime,
            arguments.runtime_candidate,
            requires_cdi=bool(devices),
        )
        if runtime == "proot":
            runtime_tmp = Path(tempfile.mkdtemp(prefix="cloudmake-proot-tmp-"))
            runtime_tmp.chmod(0o1777)
        receipt.update(
            status="preparing",
            runner="oci",
            runtime=runtime,
            image=arguments.image,
            digest=digest,
            devices=devices,
            runtime_candidates=arguments.runtime_candidate,
            execution_policy={
                "profile": "least-privileged-compute-v1",
                "privileged": False,
                "no_new_privileges": True,
                "effective_capabilities": [],
                "host_credentials": "not-injected",
                "host_mount_scope": (
                    "workspace,tmp,kernel-api,cdi"
                    if runtime == "proot"
                    else "workspace,tmp,cdi"
                ),
            },
        )
        base, image, identity = prepare(
            runtime=runtime,
            reference=arguments.image,
            digest=digest,
            source=arguments.source.resolve(),
            devices=devices,
            cache=arguments.cache.resolve(),
            internal_result=arguments.result.resolve().with_name(
                f".{arguments.result.name}.runtime"
            ),
            rootless_workspace_owner=arguments.rootless_workspace_owner,
            cdi_directories=arguments.cdi_spec_dir,
            runtime_tmp=runtime_tmp,
            runtime_home=(
                arguments.runtime_home.resolve()
                if arguments.runtime_home is not None
                else None
            ),
        )
        receipt["image_inspection"] = image
        if identity is not None:
            receipt["workspace_identity"] = identity
        run_checked(
            [*base, "--version"], capture=True, description="OCI Make preflight",
        )
        if arguments.mode == "preflight":
            receipt["status"] = "ready"
            atomic_json(arguments.result, receipt)
            print(
                f"[cloudmake] runner=oci runtime={runtime} image={arguments.image} "
                "preflight=ready",
                flush=True,
            )
            return 0

        print(
            f"[cloudmake] runner=oci runtime={runtime} image={arguments.image} "
            "preflight=ready",
            flush=True,
        )
        target = decode_value(arguments.target_b64, "target")
        if not target or "\n" in target:
            raise RunnerError("project target must be non-empty and contain no newline")
        project_arguments = decode_arguments(arguments.arguments_b64)
        command = [
            *base,
            "-f",
            makefile,
            *project_arguments,
            f"-j{arguments.jobs}",
            "--",
            target,
        ]
        receipt.update(status="submitted", target=target)
        atomic_json(arguments.result, receipt)
        completed = subprocess.run(command, check=False)
        if runtime == "crun":
            validate_internal_execution(
                arguments.result.resolve().with_name(f".{arguments.result.name}.runtime"),
                completed.returncode,
                runtime,
            )
        receipt.update(
            status="succeeded" if completed.returncode == 0 else "target-failed",
            exit_code=completed.returncode,
        )
        atomic_json(arguments.result, receipt)
        return completed.returncode
    except RunnerError as error:
        receipt.update(status="infrastructure-failed", error=str(error))
        atomic_json(arguments.result, receipt)
        print(f"[cloudmake] OCI infrastructure failure: {error}", file=sys.stderr)
        return EX_SOFTWARE
    finally:
        if runtime_tmp is not None:
            shutil.rmtree(runtime_tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
