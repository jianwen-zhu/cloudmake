from __future__ import annotations

import base64
import contextlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

import pytest

from conftest import PROJECT_ROOT, run_command, write_executable


TOOL = PROJECT_ROOT / "tools" / "oci_runner.py"
RESULT_TOOL = PROJECT_ROOT / "tools" / "oci_result.py"
IMAGE = "registry.example/tools/build@sha256:" + "a" * 64


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def encoded(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii")


def fake_runtime(fake_bin: Path) -> Path:
    log = fake_bin.parent / "runtime.jsonl"
    write_executable(
        fake_bin / "podman",
        r'''#!/usr/bin/env python3
import json
import os
from pathlib import Path
import platform
import sys
with Path(os.environ["OCI_TEST_LOG"]).open("a", encoding="utf-8") as stream:
    stream.write(json.dumps(sys.argv[1:]) + "\n")
if sys.argv[1:3] == ["image", "inspect"]:
    host_arch = {"x86_64": "amd64", "aarch64": "arm64", "arm64": "arm64"}.get(platform.machine(), platform.machine())
    print(json.dumps([{"RepoDigests": [sys.argv[-1]], "Os": os.environ.get("OCI_TEST_OS", "linux"), "Architecture": os.environ.get("OCI_TEST_ARCH", host_arch)}]))
elif sys.argv[1:2] == ["run"] and "--version" not in sys.argv:
    raise SystemExit(int(os.environ.get("OCI_TEST_TARGET_EXIT", "0")))
''',
    )
    return log


def invoke(
    tmp_path: Path,
    fake_bin: Path,
    *extra: str,
    target_exit: int = 0,
):
    source = tmp_path / "project"
    source.mkdir(exist_ok=True)
    (source / "Makefile").write_text("all:\n\t@true\n", encoding="utf-8")
    result = tmp_path / "result.json"
    log = fake_runtime(fake_bin)
    environment = {
        "PATH": f"{fake_bin}{os.pathsep}/usr/bin:/bin",
        "OCI_TEST_LOG": str(log),
        "OCI_TEST_TARGET_EXIT": str(target_exit),
    }
    completed = run_command(
        [
            sys.executable,
            TOOL,
            "--image",
            IMAGE,
            "--runtime",
            "podman",
            "--source",
            source,
            "--cache",
            tmp_path / "cache",
            "--result",
            result,
            *extra,
        ],
        cwd=tmp_path,
        env=environment,
        check=False,
    )
    calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    return completed, json.loads(result.read_text(encoding="utf-8")), calls


def test_preflight_pulls_digest_and_checks_make_without_submitting_target(
    tmp_path: Path, fake_bin: Path
) -> None:
    completed, receipt, calls = invoke(
        tmp_path, fake_bin, "--mode", "preflight", "--device", "nvidia.com/gpu=all"
    )

    assert completed.returncode == 0
    assert calls[0] == ["info"]
    assert calls[1] == ["pull", IMAGE]
    assert calls[2] == ["image", "inspect", IMAGE]
    assert calls[3][-2:] == [IMAGE, "--version"]
    assert ["--device", "nvidia.com/gpu=all"] == calls[3][
        calls[3].index("--device") : calls[3].index("--device") + 2
    ]
    assert receipt["status"] == "ready"
    assert receipt["runtime"] == "podman"
    assert receipt["digest"] == "sha256:" + "a" * 64


def test_target_failure_is_preserved_after_exactly_one_submission(
    tmp_path: Path, fake_bin: Path
) -> None:
    completed, receipt, calls = invoke(
        tmp_path,
        fake_bin,
        "--mode",
        "run",
        "--target-b64",
        encoded("route"),
        "--arguments-b64",
        encoded(json.dumps(["DESIGN=gcd"])),
        "--jobs",
        "3",
        target_exit=2,
    )

    assert completed.returncode == 2
    assert len(calls) == 5
    assert calls[3][-1] == "--version"
    assert calls[4][-6:] == ["-f", "Makefile", "DESIGN=gcd", "-j3", "--", "route"]
    assert receipt["status"] == "target-failed"
    assert receipt["exit_code"] == 2


def test_terminal_receipt_rejects_remote_process_status_mismatch(tmp_path: Path) -> None:
    result = tmp_path / "result.json"
    result.write_text(
        json.dumps(
            {
                "schema": 1,
                "status": "succeeded",
                "target": "route",
                "exit_code": 0,
            }
        ),
        encoding="utf-8",
    )

    completed = run_command(
        [
            sys.executable,
            RESULT_TOOL,
            "--result",
            result,
            "--expect",
            "terminal",
            "--process-status",
            "255",
        ],
        cwd=tmp_path,
        check=False,
    )

    assert completed.returncode == 70
    assert "does not match target receipt status 0" in completed.stdout


def test_invalid_reference_is_rejected_before_runtime_contact(
    tmp_path: Path, fake_bin: Path
) -> None:
    source = tmp_path / "project"
    source.mkdir()
    result = tmp_path / "result.json"
    log = fake_runtime(fake_bin)
    completed = run_command(
        [
            sys.executable,
            TOOL,
            "--mode",
            "preflight",
            "--image",
            "registry.example/tools/build:latest",
            "--runtime",
            "podman",
            "--source",
            source,
            "--cache",
            tmp_path / "cache",
            "--result",
            result,
        ],
        cwd=tmp_path,
        env={"PATH": f"{fake_bin}{os.pathsep}/usr/bin:/bin", "OCI_TEST_LOG": str(log)},
        check=False,
    )

    assert completed.returncode == 70
    assert not log.exists()
    assert "immutable references" in completed.stdout
    assert json.loads(result.read_text(encoding="utf-8"))["status"] == "infrastructure-failed"


def test_proot_fallback_rejects_cdi_instead_of_ignoring_it(tmp_path: Path) -> None:
    module = load("oci_runner_proot_cdi")

    with pytest.raises(module.RunnerError, match="cannot apply CDI"):
        module.prepare(
            runtime="proot",
            reference=IMAGE,
            digest="sha256:" + "a" * 64,
            source=tmp_path,
            devices=["nvidia.com/gpu=all"],
            cache=tmp_path / "cache",
        )


def test_dynamic_runtime_probe_tries_multiple_backend_options(monkeypatch) -> None:
    module = load("oci_runner_multiple_runtime_options")
    monkeypatch.setattr(module.shutil, "which", lambda name: f"/usr/bin/{name}")
    probes: list[str] = []

    def fake_run(command, **kwargs):
        probes.append(command[0])
        status = 1 if command[0] == "podman" else 0
        return subprocess.CompletedProcess(command, status, "podman is not running\n")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    selected = module.select_runtime(
        "auto", ["podman", "docker", "nerdctl", "proot"]
    )

    assert selected == "docker"
    assert probes == ["podman", "docker"]


def test_dynamic_runtime_probe_skips_non_cdi_fallbacks(monkeypatch) -> None:
    module = load("oci_runner_cdi_runtime_options")
    monkeypatch.setattr(module.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 0, ""),
    )

    selected = module.select_runtime(
        "auto", ["proot", "docker"], requires_cdi=True
    )

    assert selected == "docker"


def test_proot_uses_only_validated_image_environment(tmp_path: Path) -> None:
    module = load("oci_runner_proot_environment")
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "config.json").write_text(
        json.dumps({"process": {"env": ["PATH=/tools/bin:/usr/bin", "TOOL_HOME=/tools"]}}),
        encoding="utf-8",
    )

    command = module.proot_base_command(bundle, tmp_path)

    env_index = command.index("/usr/bin/env")
    assert command[env_index : env_index + 3] == ["/usr/bin/env", "-i", "HOME=/tmp"]
    assert "PATH=/tools/bin:/usr/bin" in command
    assert "TOOL_HOME=/tools" in command
    assert "AWS_SECRET_ACCESS_KEY" not in " ".join(command)
    assert command[-1] == "make"


def test_root_proot_requires_and_drops_to_backend_selected_identity(
    tmp_path: Path, monkeypatch
) -> None:
    module = load("oci_runner_rootless_identity")
    source = tmp_path / "source"
    source.mkdir()
    (source / "file").write_text("value\n", encoding="utf-8")
    ownership: list[tuple[Path, int, int]] = []
    monkeypatch.setattr(module.os, "geteuid", lambda: 0)
    monkeypatch.setattr(module.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        module.os,
        "chown",
        lambda path, uid, gid, **kwargs: ownership.append((Path(path), uid, gid)),
    )

    with pytest.raises(module.RunnerError, match="cannot safely translate"):
        module.proot_identity_prefix(source, None)
    prefix, identity = module.proot_identity_prefix(source, "65534:65534")

    assert prefix == [
        "/usr/bin/setpriv",
        "--reuid=65534",
        "--regid=65534",
        "--clear-groups",
    ]
    assert identity == "65534:65534"
    assert (source / "file", 65534, 65534) in ownership
    assert (source, 65534, 65534) in ownership


def test_chroot_command_uses_private_receipt_and_clean_image_environment(
    tmp_path: Path,
) -> None:
    module = load("oci_runner_chroot_command")
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "config.json").write_text(
        json.dumps({"process": {"env": ["PATH=/tools/bin:/usr/bin", "TOOLS=/tools"]}}),
        encoding="utf-8",
    )
    internal_result = tmp_path / "internal.json"

    command = module.chroot_base_command(
        bundle, tmp_path / "source", "65534:65534", internal_result
    )

    assert command[:3] == [
        sys.executable,
        str(TOOL),
        "--internal-chroot-exec",
    ]
    assert str(internal_result) in command
    assert command[-1] == "make"
    assert "PATH=/tools/bin:/usr/bin" in command
    assert "TOOLS=/tools" in command
    assert "AWS_SECRET_ACCESS_KEY" not in " ".join(command)


def test_chroot_execution_preserves_completed_target_status(
    tmp_path: Path, monkeypatch
) -> None:
    module = load("oci_runner_chroot_transaction")
    bundle = tmp_path / "bundle"
    rootfs = bundle / "rootfs"
    rootfs.mkdir(parents=True)
    source = tmp_path / "source"
    source.mkdir()
    (source / "input.txt").write_text("before\n", encoding="utf-8")
    result = tmp_path / "internal.json"
    monkeypatch.setattr(module, "chown_workspace", lambda *_: None)
    monkeypatch.setattr(
        module, "restricted_chroot_mounts", lambda *_: contextlib.nullcontext()
    )

    def fake_run(command, **kwargs):
        (source / "output.txt").write_text("after\n", encoding="utf-8")
        return subprocess.CompletedProcess(command, 70)

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    exit_code = module.internal_chroot_exec(
        [
            str(bundle),
            str(source),
            "65534:65534",
            str(result),
            "--",
            "/usr/bin/env",
            "-i",
            "make",
            "--",
            "target",
        ]
    )

    assert exit_code == 70
    assert (source / "output.txt").read_text(encoding="utf-8") == "after\n"
    assert json.loads(result.read_text(encoding="utf-8")) == {
        "schema": 1,
        "status": "completed",
        "exit_code": 70,
    }
    module.validate_chroot_execution(result, 70)


def test_chroot_symlink_workspace_is_infrastructure_failure(
    tmp_path: Path, monkeypatch
) -> None:
    module = load("oci_runner_chroot_stranded")
    bundle = tmp_path / "bundle"
    rootfs = bundle / "rootfs"
    rootfs.mkdir(parents=True)
    guest = rootfs / "workspace"
    guest.symlink_to(tmp_path)
    source = tmp_path / "source"
    source.mkdir()
    result = tmp_path / "internal.json"

    with pytest.raises(module.RunnerError, match="must not be a symbolic link"):
        module.internal_chroot_exec(
            [
                str(bundle),
                str(source),
                "65534:65534",
                str(result),
                "--",
                "/usr/bin/env",
                "-i",
                "make",
                "--",
                "target",
            ]
        )

    receipt = json.loads(result.read_text(encoding="utf-8"))
    assert receipt["status"] == "infrastructure-failed"
    assert "must not be a symbolic link" in receipt["error"]
    assert guest.is_symlink()


def test_chroot_mount_profile_is_nosuid_and_workspace_bounded(
    tmp_path: Path, monkeypatch
) -> None:
    module = load("oci_runner_chroot_mounts")
    rootfs = tmp_path / "rootfs"
    source = tmp_path / "source"
    workspace = rootfs / "workspace"
    runtime_tmp = tmp_path / "runtime-tmp"
    rootfs.mkdir()
    source.mkdir()
    workspace.mkdir()
    runtime_tmp.mkdir()
    commands: list[list[str]] = []
    cleanup: list[list[str]] = []

    def fake_checked(command, **kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    def fake_run(command, **kwargs):
        cleanup.append(command)
        return subprocess.CompletedProcess(command, 0, "")

    monkeypatch.setattr(module, "run_checked", fake_checked)
    monkeypatch.setattr(module.subprocess, "run", fake_run)

    with module.restricted_chroot_mounts(rootfs, source, workspace, runtime_tmp):
        pass

    assert ["mount", "--bind", str(rootfs), str(rootfs)] in commands
    assert [
        "mount",
        "-o",
        "remount,bind,ro,nosuid,nodev",
        str(rootfs),
    ] in commands
    assert ["mount", "--bind", "/proc", str(rootfs / "proc")] in commands
    assert [
        "mount",
        "-o",
        "remount,bind,ro,nosuid,nodev,noexec",
        str(rootfs / "proc"),
    ] in commands
    assert ["mount", "--bind", str(source), str(workspace)] in commands
    assert [
        "mount",
        "--bind",
        str(runtime_tmp),
        str(rootfs / "tmp"),
    ] in commands
    assert [
        "mount",
        "-o",
        "remount,bind,rw,nosuid,nodev",
        str(workspace),
    ] in commands
    assert cleanup[-1] == ["umount", str(rootfs)]


def test_chroot_rejects_symlink_runtime_mountpoint(tmp_path: Path) -> None:
    module = load("oci_runner_chroot_symlink")
    rootfs = tmp_path / "rootfs"
    rootfs.mkdir()
    (rootfs / "proc").symlink_to(tmp_path)

    with pytest.raises(module.RunnerError, match="must not be a symbolic link"):
        with module.restricted_chroot_mounts(
            rootfs,
            tmp_path / "source",
            rootfs / "workspace",
            tmp_path / "runtime-tmp",
        ):
            pass


def test_terminal_receipt_distinguishes_target_exit_70_from_infrastructure(
    tmp_path: Path,
) -> None:
    result = tmp_path / "result.json"
    result.write_text(
        json.dumps(
            {
                "schema": 1,
                "status": "target-failed",
                "target": "lint",
                "exit_code": 70,
            }
        ),
        encoding="utf-8",
    )

    completed = run_command(
        [sys.executable, RESULT_TOOL, "--result", result, "--expect", "terminal"],
        cwd=tmp_path,
        check=False,
    )

    assert completed.returncode == 70
    assert "target 'lint' failed with exit status 70" in completed.stdout

    result.write_text(
        json.dumps(
            {
                "schema": 1,
                "status": "infrastructure-failed",
                "error": "restricted chroot mount failed",
            }
        ),
        encoding="utf-8",
    )
    completed = run_command(
        [sys.executable, RESULT_TOOL, "--result", result, "--expect", "terminal"],
        cwd=tmp_path,
        check=False,
    )
    assert completed.returncode == 70
    assert "OCI infrastructure failure: restricted chroot mount failed" in completed.stdout
    assert "target '" not in completed.stdout


def test_runtime_preflight_may_prove_cross_architecture_emulation(
    tmp_path: Path, fake_bin: Path
) -> None:
    completed, receipt, calls = invoke(tmp_path, fake_bin, "--mode", "preflight")
    assert completed.returncode == 0
    assert calls[2] == ["image", "inspect", IMAGE]

    source = tmp_path / "other-project"
    source.mkdir()
    result = tmp_path / "wrong-platform.json"
    completed = run_command(
        [
            sys.executable,
            TOOL,
            "--mode",
            "preflight",
            "--image",
            IMAGE,
            "--runtime",
            "podman",
            "--source",
            source,
            "--cache",
            tmp_path / "other-cache",
            "--result",
            result,
        ],
        cwd=tmp_path,
        env={
            "PATH": f"{fake_bin}{os.pathsep}/usr/bin:/bin",
            "OCI_TEST_LOG": str(fake_bin.parent / "wrong-platform.jsonl"),
            "OCI_TEST_ARCH": "amd64" if platform.machine() in {"arm64", "aarch64"} else "arm64",
        },
        check=False,
    )
    assert completed.returncode == 0
    receipt = json.loads(result.read_text(encoding="utf-8"))
    assert receipt["status"] == "ready"
    assert receipt["image_inspection"]["architecture_match"] is False


def test_runtime_inspection_rejects_non_linux_image(
    tmp_path: Path, fake_bin: Path
) -> None:
    source = tmp_path / "project"
    source.mkdir()
    result = tmp_path / "result.json"
    log = fake_runtime(fake_bin)

    completed = run_command(
        [
            sys.executable,
            TOOL,
            "--mode",
            "preflight",
            "--image",
            IMAGE,
            "--runtime",
            "podman",
            "--source",
            source,
            "--cache",
            tmp_path / "cache",
            "--result",
            result,
        ],
        cwd=tmp_path,
        env={
            "PATH": f"{fake_bin}{os.pathsep}/usr/bin:/bin",
            "OCI_TEST_LOG": str(log),
            "OCI_TEST_OS": "windows",
        },
        check=False,
    )

    assert completed.returncode == 70
    assert "unsupported operating system 'windows'" in completed.stdout
    assert json.loads(result.read_text(encoding="utf-8"))["status"] == "infrastructure-failed"


@pytest.mark.parametrize(
    "value",
    ["gpu", "nvidia.com/gpu", "nvidia.com/gpu=", "NVIDIA.com/gpu=all", "../gpu=all"],
)
def test_invalid_cdi_device_names_are_rejected(value: str) -> None:
    module = load("oci_runner_invalid_device_" + str(abs(hash(value))))
    with pytest.raises(module.RunnerError, match="invalid CDI device"):
        module.device_name(value)
