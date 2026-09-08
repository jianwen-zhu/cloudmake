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
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Iterator


IMAGE = re.compile(r"^([^\s@]+)@sha256:([0-9a-f]{64})$")
CDI_DEVICE = re.compile(
    r"^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?/[A-Za-z0-9_.-]+=[A-Za-z0-9_.-]+$"
)
RUNTIMES = ("auto", "podman", "docker", "nerdctl", "proot", "chroot")
NATIVE_RUNTIMES = ("podman", "docker", "nerdctl")
CHROOT_DEVICES = ("null", "zero", "full", "random", "urandom")
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
    command: list[str], *, capture: bool = False, description: str
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
    if candidate == "chroot":
        if os.geteuid() != 0:
            return False, "requires a root VM adapter"
        required = ("skopeo", "umoci", "mount", "umount")
    elif candidate == "proot":
        required = ("skopeo", "umoci", "proot")
    else:
        required = (candidate,)
    missing = [name for name in required if shutil.which(name) is None]
    if missing:
        return False, "missing " + ", ".join(missing)
    if candidate not in NATIVE_RUNTIMES:
        return True, "ready"
    try:
        completed = subprocess.run(
            [candidate, "info"],
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
    declared = candidates or [*NATIVE_RUNTIMES, "proot"]
    if len(declared) != len(set(declared)):
        raise RunnerError("OCI runtime candidate list contains duplicates")
    invalid = [candidate for candidate in declared if candidate not in RUNTIMES[1:]]
    if invalid:
        raise RunnerError("invalid OCI runtime candidate(s): " + ", ".join(invalid))
    choices = [requested] if requested != "auto" else declared
    if requires_cdi:
        choices = [candidate for candidate in choices if candidate in NATIVE_RUNTIMES]
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


def materialize_proot(
    *, reference: str, digest: str, cache_root: Path
) -> tuple[Path, dict[str, Any]]:
    image_cache = cache_root / "images" / digest.removeprefix("sha256:")
    bundle = image_cache / "bundle"
    receipt = image_cache / "receipt.json"
    with cache_lock(image_cache):
        if receipt.is_file() and (bundle / "rootfs").is_dir():
            try:
                saved = json.loads(receipt.read_text(encoding="utf-8"))
            except Exception:
                saved = {}
            if saved.get("reference") == reference and saved.get("digest") == digest:
                bundle.chmod(0o755)
                return bundle, saved.get("image", {"requested_digest": digest})

        image = inspect_with_skopeo(reference, digest)
        staging = Path(tempfile.mkdtemp(prefix=".image-", dir=image_cache))
        layout = staging / "layout"
        unpacked = staging / "bundle"
        try:
            run_checked(
                ["skopeo", "copy", f"docker://{reference}", f"oci:{layout}:cloudmake"],
                description="OCI image pull",
            )
            run_checked(
                ["umoci", "unpack", "--rootless", "--image", f"{layout}:cloudmake", str(unpacked)],
                description="OCI image materialization",
            )
            if bundle.exists():
                shutil.rmtree(bundle)
            os.replace(unpacked, bundle)
            # umoci creates the bundle beneath a 0700 staging directory. PRoot
            # must run unprivileged even when the managed VM account is root.
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
    command = [runtime, "run", "--rm", "--workdir", "/workspace"]
    if runtime == "podman":
        command.extend(["--userns=keep-id"])
    else:
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


def proot_identity_prefix(source: Path, owner: str | None) -> tuple[list[str], str]:
    if os.geteuid() != 0:
        if owner is not None:
            raise RunnerError("a PRoot workspace owner may be supplied only by a root VM adapter")
        return [], f"{os.getuid()}:{os.getgid()}"
    if owner is None:
        raise RunnerError(
            "PRoot cannot safely translate an OCI root while running as root; "
            "the backend must select an unprivileged workspace owner"
        )
    uid, gid = workspace_owner(owner)
    setpriv = shutil.which("setpriv")
    if setpriv is None:
        raise RunnerError("root PRoot execution requires the setpriv command")
    chown_workspace(source, uid, gid)
    return [setpriv, f"--reuid={uid}", f"--regid={gid}", "--clear-groups"], owner


def proot_base_command(
    bundle: Path, source: Path, identity_prefix: list[str] | None = None
) -> list[str]:
    return [
        *(identity_prefix or []),
        "proot",
        "-r",
        str(bundle / "rootfs"),
        "-b",
        f"{source}:/workspace",
        "-w",
        "/workspace",
        "/usr/bin/env",
        "-i",
        *oci_process_environment(bundle),
        "make",
    ]


def chroot_base_command(
    bundle: Path, source: Path, owner: str, internal_result: Path
) -> list[str]:
    return [
        sys.executable,
        os.fspath(Path(__file__).resolve()),
        "--internal-chroot-exec",
        os.fspath(bundle),
        os.fspath(source),
        owner,
        os.fspath(internal_result),
        "--",
        "/usr/bin/env",
        "-i",
        *oci_process_environment(bundle),
        "make",
    ]


def safe_runtime_directory(rootfs: Path, name: str) -> Path:
    path = rootfs / name
    if path.is_symlink():
        raise RunnerError(f"OCI image {name!r} runtime path must not be a symbolic link")
    path.mkdir(mode=0o755, exist_ok=True)
    if not path.is_dir():
        raise RunnerError(f"OCI image {name!r} runtime path is not a directory")
    return path


@contextlib.contextmanager
def restricted_chroot_mounts(
    rootfs: Path, source: Path, workspace: Path, runtime_tmp: Path
) -> Iterator[None]:
    proc = safe_runtime_directory(rootfs, "proc")
    dev = safe_runtime_directory(rootfs, "dev")
    temporary = safe_runtime_directory(rootfs, "tmp")
    device_mounts: list[tuple[Path, Path]] = []
    for name in CHROOT_DEVICES:
        device_source = Path("/dev") / name
        if not device_source.exists():
            continue
        target = dev / name
        if target.is_symlink() or (target.exists() and not target.is_file()):
            raise RunnerError(f"OCI image device mount point /dev/{name} is unsafe")
        target.touch(exist_ok=True)
        device_mounts.append((device_source, target))
    mounted: list[Path] = []
    try:
        run_checked(
            ["mount", "--bind", os.fspath(rootfs), os.fspath(rootfs)],
            capture=True,
            description="restricted chroot rootfs bind",
        )
        mounted.append(rootfs)
        run_checked(
            ["mount", "-o", "remount,bind,ro,nosuid,nodev", os.fspath(rootfs)],
            capture=True,
            description="restricted chroot read-only rootfs remount",
        )
        run_checked(
            ["mount", "--bind", "/proc", os.fspath(proc)],
            capture=True,
            description="restricted chroot proc bind",
        )
        mounted.append(proc)
        run_checked(
            [
                "mount",
                "-o",
                "remount,bind,ro,nosuid,nodev,noexec",
                os.fspath(proc),
            ],
            capture=True,
            description="restricted chroot read-only proc remount",
        )
        for device_source, target in device_mounts:
            run_checked(
                ["mount", "--bind", os.fspath(device_source), os.fspath(target)],
                capture=True,
                description=f"restricted chroot /dev/{target.name} bind",
            )
            mounted.append(target)
        run_checked(
            ["mount", "--bind", os.fspath(runtime_tmp), os.fspath(temporary)],
            capture=True,
            description="restricted chroot temporary-directory bind",
        )
        mounted.append(temporary)
        run_checked(
            [
                "mount",
                "-o",
                "remount,bind,rw,nosuid,nodev",
                os.fspath(temporary),
            ],
            capture=True,
            description="restricted chroot temporary-directory remount",
        )
        run_checked(
            ["mount", "--bind", os.fspath(source), os.fspath(workspace)],
            capture=True,
            description="restricted chroot project bind",
        )
        mounted.append(workspace)
        run_checked(
            [
                "mount",
                "-o",
                "remount,bind,rw,nosuid,nodev",
                os.fspath(workspace),
            ],
            capture=True,
            description="restricted chroot project remount",
        )
        yield
    finally:
        cleanup_errors: list[str] = []
        for path in reversed(mounted):
            completed = subprocess.run(
                ["umount", os.fspath(path)],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            if completed.returncode:
                cleanup_errors.append(
                    f"{path}: {(completed.stdout or '').strip() or completed.returncode}"
                )
        if cleanup_errors:
            raise RunnerError(
                "restricted chroot mount cleanup failed: " + "; ".join(cleanup_errors)
            )


def internal_chroot_exec(arguments: list[str]) -> int:
    if len(arguments) < 6 or arguments[4] != "--":
        raise RunnerError("invalid internal chroot invocation")
    bundle = Path(arguments[0]).resolve()
    source = Path(arguments[1]).resolve()
    uid, gid = workspace_owner(arguments[2])
    internal_result = Path(arguments[3]).resolve()
    command = arguments[5:]
    rootfs = bundle / "rootfs"
    guest = rootfs / "workspace"
    internal_result.unlink(missing_ok=True)
    completed: subprocess.CompletedProcess[Any] | None = None
    try:
        with cache_lock(bundle):
            if not rootfs.is_dir() or not source.is_dir():
                raise RunnerError("restricted chroot root or project workspace is unavailable")
            guest = safe_runtime_directory(rootfs, "workspace")
            chown_workspace(source, uid, gid)

            def enter_guest() -> None:
                os.chroot(rootfs)
                os.chdir("/workspace")
                os.setgroups([])
                os.setgid(gid)
                os.setuid(uid)

            with tempfile.TemporaryDirectory(prefix=".runtime-", dir=bundle) as temporary:
                runtime_tmp = Path(temporary)
                runtime_tmp.chmod(0o1777)
                with restricted_chroot_mounts(rootfs, source, guest, runtime_tmp):
                    completed = subprocess.run(
                        command,
                        check=False,
                        env={},
                        close_fds=True,
                        preexec_fn=enter_guest,
                    )
        atomic_json(
            internal_result,
            {
                "schema": 1,
                "status": "completed",
                "exit_code": completed.returncode,
            },
        )
        return completed.returncode
    except (OSError, subprocess.SubprocessError) as error:
        failure = RunnerError(f"restricted chroot execution failed: {error}")
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
) -> tuple[list[str], dict[str, Any], str | None]:
    if not source.is_dir():
        raise RunnerError(f"project workspace is unavailable: {source}")
    if runtime == "proot":
        if devices:
            raise RunnerError(
                "the PRoot OCI fallback cannot apply CDI device edits; select a "
                "CDI-capable native runtime"
            )
        bundle, image = materialize_proot(
            reference=reference, digest=digest, cache_root=cache
        )
        identity_prefix, identity = proot_identity_prefix(
            source, rootless_workspace_owner
        )
        return proot_base_command(bundle, source, identity_prefix), image, identity

    if runtime == "chroot":
        if devices:
            raise RunnerError(
                "the restricted chroot OCI runtime cannot apply CDI device edits; "
                "select a CDI-capable native runtime"
            )
        if rootless_workspace_owner is None:
            raise RunnerError(
                "the restricted chroot OCI runtime requires a non-root workspace owner"
            )
        if internal_result is None:
            raise RunnerError(
                "the restricted chroot OCI runtime requires an internal result path"
            )
        identity = ":".join(str(value) for value in workspace_owner(rootless_workspace_owner))
        bundle, image = materialize_proot(
            reference=reference, digest=digest, cache_root=cache
        )
        return (
            chroot_base_command(bundle, source, identity, internal_result),
            image,
            identity,
        )

    run_checked([runtime, "pull", reference], description=f"{runtime} image pull")
    image = (
        inspect_with_skopeo(reference, digest)
        if shutil.which("skopeo")
        else inspect_with_runtime(runtime, reference, digest)
    )
    return native_base_command(runtime, source, reference, devices), image, None


def validate_chroot_execution(path: Path, exit_code: int) -> None:
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except Exception as error:
        raise RunnerError(
            "restricted chroot execution did not produce a valid result receipt"
        ) from error
    if receipt.get("schema") != 1 or receipt.get("status") != "completed":
        detail = receipt.get("error", "restricted chroot execution did not complete")
        raise RunnerError(str(detail))
    if receipt.get("exit_code") != exit_code:
        raise RunnerError("restricted chroot execution result did not match process status")


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
    result.add_argument("--result", type=Path, required=True)
    return result


def main() -> int:
    if sys.argv[1:2] == ["--internal-chroot-exec"]:
        try:
            return internal_chroot_exec(sys.argv[2:])
        except RunnerError as error:
            print(f"[cloudmake] OCI infrastructure failure: {error}", file=sys.stderr)
            return EX_SOFTWARE
    arguments = parser().parse_args()
    receipt: dict[str, Any] = {"schema": 1, "mode": arguments.mode}
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
        receipt.update(
            status="preparing",
            runner="oci",
            runtime=runtime,
            image=arguments.image,
            digest=digest,
            devices=devices,
            runtime_candidates=arguments.runtime_candidate,
        )
        base, image, identity = prepare(
            runtime=runtime,
            reference=arguments.image,
            digest=digest,
            source=arguments.source.resolve(),
            devices=devices,
            cache=arguments.cache.resolve(),
            internal_result=arguments.result.resolve().with_name(
                f".{arguments.result.name}.chroot"
            ),
            rootless_workspace_owner=arguments.rootless_workspace_owner,
        )
        receipt["image_inspection"] = image
        if identity is not None:
            receipt["workspace_identity"] = identity
        run_checked(
            [*base, "--version"], capture=True, description="OCI Make preflight"
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
        if runtime == "chroot":
            validate_chroot_execution(
                arguments.result.resolve().with_name(f".{arguments.result.name}.chroot"),
                completed.returncode,
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


if __name__ == "__main__":
    raise SystemExit(main())
