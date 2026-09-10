from __future__ import annotations

import base64
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


def test_materialized_rootfs_is_recreated_from_persistent_oci_layout(
    tmp_path: Path, monkeypatch
) -> None:
    module = load("oci_runner_persistent_layout")
    digest = "sha256:" + "a" * 64
    reference = "registry.example/tools/build@" + digest
    calls: list[list[str]] = []

    monkeypatch.setattr(
        module,
        "inspect_with_skopeo",
        lambda *_arguments: {"requested_digest": digest, "architecture": "amd64"},
    )

    def run_checked(command, **_arguments):
        calls.append([str(value) for value in command])
        if command[:2] == ["skopeo", "copy"]:
            layout = Path(command[-1].removeprefix("oci:").rsplit(":", 1)[0])
            layout.mkdir(parents=True)
            (layout / "oci-layout").write_text("{}", encoding="utf-8")
            (layout / "index.json").write_text("{}", encoding="utf-8")
        elif command[:2] == ["umoci", "unpack"]:
            bundle = Path(command[-1])
            (bundle / "rootfs").mkdir(parents=True)
            (bundle / "config.json").write_text("{}", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(module, "run_checked", run_checked)
    cache = tmp_path / "cache"
    bundle, _ = module.materialize_bundle(
        reference=reference, digest=digest, cache_root=cache
    )
    image_cache = cache / "images" / ("a" * 64)
    assert (image_cache / "layout/oci-layout").is_file()
    assert (image_cache / "layout/index.json").is_file()
    assert (bundle / "rootfs").is_dir()
    assert [command[:2] for command in calls] == [
        ["skopeo", "copy"],
        ["umoci", "unpack"],
    ]

    import shutil

    shutil.rmtree(bundle)
    calls.clear()
    monkeypatch.setattr(
        module,
        "inspect_with_skopeo",
        lambda *_arguments: (_ for _ in ()).throw(
            AssertionError("cached OCI layout must not contact the registry")
        ),
    )
    restored, image = module.materialize_bundle(
        reference=reference, digest=digest, cache_root=cache
    )

    assert (restored / "rootfs").is_dir()
    assert image["architecture"] == "amd64"
    assert len(calls) == 1
    assert calls[0][:2] == ["umoci", "unpack"]
    assert str(image_cache / "layout") in calls[0][calls[0].index("--image") + 1]


def test_proot_identifies_guest_and_prior_vm_link_repairs(
    tmp_path: Path,
) -> None:
    module = load("oci_runner_proot_guest_link_rehydration")
    digest = "a" * 64
    rootfs = tmp_path / f"cache/oci/images/{digest}/bundle/rootfs"
    executable = rootfs / "opt/conda/bin/python3"
    executable.parent.mkdir(parents=True)
    executable.write_text("python", encoding="utf-8")
    executable.chmod(0o755)
    image_home = tmp_path / "checkpoint-home"
    (image_home / "venv/bin").mkdir(parents=True)
    python = image_home / "venv/bin/python3"
    python.symlink_to("/opt/conda/bin/python3")
    python_short = image_home / "venv/bin/python"
    python_short.symlink_to("python3")
    old_python = image_home / "venv/bin/python-old"
    old_python.symlink_to(
        f"/tmp/cloud-build/workspace/cache/oci/images/{digest}/bundle/rootfs/"
        "opt/conda/bin/python3"
    )
    (image_home / "missing").symlink_to("/does/not/exist")
    (image_home / "relative").symlink_to("venv/bin/python3")

    repairs = module.proot_guest_link_repairs(image_home, rootfs)

    assert repairs == [
        ("", "python3", "/home/cloudmake/venv/bin/python"),
        (
            str(executable.resolve()),
            "/opt/conda/bin/python3",
            "/home/cloudmake/venv/bin/python-old",
        ),
        (
            str(executable.resolve()),
            "/opt/conda/bin/python3",
            "/home/cloudmake/venv/bin/python3",
        ),
    ]
    assert os.readlink(python) == "/opt/conda/bin/python3"
    assert os.readlink(old_python).startswith("/tmp/cloud-build/workspace/")
    assert os.readlink(image_home / "missing") == "/does/not/exist"
    assert os.readlink(image_home / "relative") == "venv/bin/python3"


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
    assert receipt["execution_policy"] == {
        "profile": "least-privileged-compute-v1",
        "privileged": False,
        "no_new_privileges": True,
        "effective_capabilities": [],
        "host_credentials": "not-injected",
        "host_mount_scope": "workspace,tmp,cdi",
    }
    assert "--read-only" in calls[3]
    assert "--cap-drop=ALL" in calls[3]
    assert "--security-opt=no-new-privileges=true" in calls[3]
    assert "/tmp:rw,nosuid,nodev" in calls[3]
    assert ["--user", f"{os.getuid()}:{os.getgid()}"] == calls[3][
        calls[3].index("--user") : calls[3].index("--user") + 2
    ]


def test_native_runtime_does_not_use_an_unrelated_host_skopeo(
    tmp_path: Path, fake_bin: Path
) -> None:
    write_executable(
        fake_bin / "skopeo",
        "#!/bin/sh\necho 'ambient skopeo must not run' >&2\nexit 99\n",
    )

    completed, receipt, calls = invoke(tmp_path, fake_bin, "--mode", "preflight")

    assert completed.returncode == 0
    assert receipt["status"] == "ready"
    assert calls[2] == ["image", "inspect", IMAGE]


@pytest.mark.parametrize("runtime", ["podman", "docker", "nerdctl"])
def test_native_runtimes_receive_the_same_least_privilege_policy(
    tmp_path: Path, runtime: str
) -> None:
    module = load(f"oci_runner_native_policy_{runtime}")
    command = module.native_base_command(
        runtime,
        tmp_path / "source",
        "registry.example/tools@sha256:" + "a" * 64,
        ["nvidia.com/gpu=all"],
    )

    assert "--privileged" not in command
    assert "--network=host" not in command
    assert "--pid=host" not in command
    assert "--read-only" in command
    assert "--cap-drop=ALL" in command
    assert "--security-opt=no-new-privileges=true" in command
    assert "/tmp:rw,nosuid,nodev" in command
    assert ["--device", "nvidia.com/gpu=all"] == command[
        command.index("--device") : command.index("--device") + 2
    ]


def test_devcontainer_environment_is_forwarded_to_native_runtime(
    tmp_path: Path,
) -> None:
    module = load("oci_runner_devcontainer_environment")

    command = module.native_base_command(
        "docker", tmp_path, IMAGE, [], ["FLOW=smoke", "TOOL_MODE=batch"]
    )

    assert command[command.index("FLOW=smoke") - 1] == "--env"
    assert command[command.index("TOOL_MODE=batch") - 1] == "--env"


def test_devcontainer_forward_port_is_loopback_only(tmp_path: Path) -> None:
    module = load("oci_runner_devcontainer_forward_port")

    command = module.native_base_command(
        "docker", tmp_path, IMAGE, [], forward_ports=[8080]
    )

    assert command[command.index("127.0.0.1:8080:8080") - 1] == "--publish"
    assert "0.0.0.0:8080:8080" not in command


def test_devcontainer_environment_overrides_image_environment(tmp_path: Path) -> None:
    module = load("oci_runner_devcontainer_environment_override")
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "config.json").write_text(
        json.dumps({"process": {"env": ["FLOW=image", "PATH=/usr/bin"]}}),
        encoding="utf-8",
    )

    environment = module.oci_process_environment(bundle, ["FLOW=project"])

    assert "FLOW=project" in environment
    assert "FLOW=image" not in environment


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


def test_proot_adapter_translates_cdi_device_to_least_privileged_bind(
    tmp_path: Path,
) -> None:
    module = load("oci_runner_proot_cdi")
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "config.json").write_text(
        json.dumps({"process": {"env": ["PATH=/usr/bin"]}}), encoding="utf-8"
    )
    cdi = tmp_path / "cdi"
    cdi.mkdir()
    (cdi / "device.json").write_text(
        json.dumps({
            "cdiVersion": "0.6.0",
            "kind": "nvidia.com/gpu",
            "devices": [{
                "name": "all",
                "containerEdits": {
                    "env": ["VISIBLE_GPU=yes"],
                    "deviceNodes": [{"path": "/dev/null", "hostPath": "/dev/null"}],
                },
            }],
        }),
        encoding="utf-8",
    )

    bindings, environment, sources = module.proot_cdi_configuration(
        bundle, ["nvidia.com/gpu=all"], [cdi]
    )

    assert bindings == [("/dev/null", "/dev/null")]
    assert "VISIBLE_GPU=yes" in environment
    assert sources == [str(cdi / "device.json")]


def test_proot_command_binds_a_fresh_runtime_tmp(tmp_path: Path) -> None:
    module = load("oci_runner_proot_tmp")
    runtime_tmp = tmp_path / "runtime-tmp"
    command = module.proot_base_command(
        tmp_path / "bundle",
        tmp_path / "source",
        environment=["PATH=/usr/bin"],
        runtime_tmp=runtime_tmp,
    )

    assert f"{runtime_tmp}:/tmp" in command


def test_proot_command_can_bind_a_runtime_home(tmp_path: Path) -> None:
    module = load("oci_runner_proot_home")
    runtime_home = tmp_path / "home"
    command = module.proot_base_command(
        tmp_path / "bundle",
        tmp_path / "source",
        environment=["HOME=/home/cloudmake", "PATH=/usr/bin"],
        runtime_home=runtime_home,
    )

    assert f"{runtime_home}:/home/cloudmake" in command
    assert "HOME=/home/cloudmake" in command


def test_proot_command_binds_safe_host_devices_and_resolver(
    tmp_path: Path, monkeypatch
) -> None:
    module = load("oci_runner_proot_host_surface")
    monkeypatch.setattr(
        module.Path,
        "is_char_device",
        lambda path: str(path) in {"/dev/null", "/dev/zero"},
    )
    monkeypatch.setattr(module.Path, "is_block_device", lambda _path: False)
    monkeypatch.setattr(
        module.Path,
        "is_dir",
        lambda path: str(path) in {"/proc", "/sys"},
    )
    monkeypatch.setattr(
        module.Path,
        "exists",
        lambda path: str(path) in {"/etc/resolv.conf", "/etc/hosts"},
    )
    monkeypatch.setattr(module.Path, "resolve", lambda path: path)

    command = module.proot_base_command(
        tmp_path / "bundle", tmp_path / "source", environment=["PATH=/usr/bin"]
    )

    assert "/dev/null:/dev/null" in command
    assert "/dev/zero:/dev/zero" in command
    assert "/dev/random:/dev/random" not in command
    assert "/etc/resolv.conf:/etc/resolv.conf" in command
    assert "/etc/hosts:/etc/hosts" in command
    assert "/proc:/proc" in command
    assert "/sys:/sys" in command


def test_proot_materializes_missing_cdi_bind_targets(tmp_path: Path) -> None:
    module = load("oci_runner_proot_bind_targets")
    rootfs = tmp_path / "rootfs"
    rootfs.mkdir()
    host_file = tmp_path / "libcuda.so.1"
    host_file.write_text("driver", encoding="utf-8")
    host_directory = tmp_path / "device-directory"
    host_directory.mkdir()

    module.prepare_proot_binding_targets(
        rootfs,
        [
            (str(host_file), "/usr/lib/x86_64-linux-gnu/libcuda.so.1"),
            (str(host_directory), "/run/cloudmake-device"),
        ],
    )

    assert (rootfs / "usr/lib/x86_64-linux-gnu/libcuda.so.1").is_file()
    assert (rootfs / "run/cloudmake-device").is_dir()


def test_proot_rejects_cdi_bind_target_beneath_image_symlink(tmp_path: Path) -> None:
    module = load("oci_runner_proot_bind_target_symlink")
    rootfs = tmp_path / "rootfs"
    rootfs.mkdir()
    (rootfs / "usr").symlink_to(tmp_path)
    host_file = tmp_path / "libcuda.so.1"
    host_file.write_text("driver", encoding="utf-8")

    with pytest.raises(module.RunnerError, match="parent escapes the image root"):
        module.prepare_proot_binding_targets(
            rootfs, [(str(host_file), "/usr/lib/libcuda.so")]
        )


def test_proot_checkpointed_home_overrides_image_home_after_cdi(
    tmp_path: Path, monkeypatch
) -> None:
    module = load("oci_runner_proot_cdi_home")
    bundle = tmp_path / "bundle"
    (bundle / "rootfs").mkdir(parents=True)
    (bundle / "config.json").write_text(
        json.dumps({"process": {"env": ["HOME=/image-user", "PATH=/usr/bin"]}}),
        encoding="utf-8",
    )
    source = tmp_path / "source"
    source.mkdir()
    runtime_home = tmp_path / "runtime-home"
    (runtime_home / "venv/bin").mkdir(parents=True)
    (runtime_home / "venv/bin/python3").symlink_to("/opt/conda/bin/python3")
    image_python = bundle / "rootfs/opt/conda/bin/python3"
    image_python.parent.mkdir(parents=True)
    image_python.write_text("python", encoding="utf-8")
    image_python.chmod(0o755)
    repair_calls: list[list[str]] = []
    monkeypatch.setattr(
        module,
        "materialize_bundle",
        lambda **_: (bundle, {"architecture": "amd64"}),
    )
    monkeypatch.setattr(
        module, "proot_identity_prefix", lambda *_: (["setpriv"], "501:20")
    )
    monkeypatch.setattr(
        module,
        "proot_cdi_configuration",
        lambda *_: (
            [("/dev/null", "/dev/null")],
            ["HOME=/image-user", "PATH=/usr/bin", "VISIBLE_GPU=yes"],
            ["/etc/cdi/gpu.json"],
        ),
    )
    monkeypatch.setattr(
        module,
        "run_checked",
        lambda command, **_: repair_calls.append(command)
        or subprocess.CompletedProcess(command, 0),
    )

    command, _, _ = module.prepare(
        runtime="proot",
        reference="registry.example/tools@sha256:" + "a" * 64,
        digest="sha256:" + "a" * 64,
        source=source,
        devices=["nvidia.com/gpu=all"],
        cache=tmp_path / "cache",
        runtime_home=runtime_home,
    )

    assert f"{runtime_home}:/home/cloudmake" in command
    assert "HOME=/home/cloudmake" in command
    assert "HOME=/image-user" not in command
    assert "VISIBLE_GPU=yes" in command
    assert repair_calls[0][-4:] == [
        "/bin/ln",
        "-snf",
        "/opt/conda/bin/python3",
        "/home/cloudmake/venv/bin/python3",
    ]
    assert repair_calls[1][-3:] == [
        "/usr/bin/test",
        "-x",
        "/home/cloudmake/venv/bin/python3",
    ]
    assert f"{image_python}:/home/cloudmake/venv/bin/python3!" not in command


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


def test_dynamic_runtime_probe_can_select_proot_cdi_adapter(monkeypatch) -> None:
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

    assert selected == "proot"


def test_dynamic_runtime_probe_selects_direct_crun_for_cdi(monkeypatch) -> None:
    module = load("oci_runner_crun_runtime_option")
    monkeypatch.setattr(module.os, "geteuid", lambda: 0)
    monkeypatch.setattr(module.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 0, "crun 1.8\n"),
    )

    selected = module.select_runtime("auto", ["crun"], requires_cdi=True)

    assert selected == "crun"


def test_removed_chroot_runtime_is_rejected_by_public_parser(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    completed = run_command(
        [
            sys.executable,
            TOOL,
            "--mode",
            "preflight",
            "--image",
            IMAGE,
            "--runtime",
            "chroot",
            "--source",
            source,
            "--cache",
            tmp_path / "cache",
            "--result",
            tmp_path / "result.json",
        ],
        cwd=tmp_path,
        check=False,
    )

    assert completed.returncode == 2
    assert "invalid choice: 'chroot'" in completed.stdout


def test_crun_base_command_enters_image_through_make(tmp_path: Path) -> None:
    module = load("oci_runner_crun_base_command")
    command = module.crun_base_command(
        tmp_path / "bundle",
        tmp_path / "source",
        "65534:65534",
        tmp_path / "result.json",
        ["nvidia.com/gpu=all"],
        [tmp_path / "cdi"],
    )

    assert command[:3] == [sys.executable, str(TOOL), "--internal-crun-exec"]
    assert command[-2:] == ["--", "make"]
    assert command[command.index("--device") + 1] == "nvidia.com/gpu=all"
    assert command[command.index("--cdi-dir") + 1] == str(tmp_path / "cdi")
    parsed = module.internal_crun_parser(command[3:])
    assert parsed.command == ["make"]
    assert parsed.device == ["nvidia.com/gpu=all"]
    assert parsed.cdi_dir == [tmp_path / "cdi"]


def test_direct_crun_adapter_applies_strict_json_cdi_edits(
    tmp_path: Path, monkeypatch
) -> None:
    module = load("oci_runner_crun_cdi_edits")
    cdi = tmp_path / "cdi"
    cdi.mkdir()
    libraries = tmp_path / "driver-libs"
    libraries.mkdir()
    device = tmp_path / "gpu0"
    device.write_text("device", encoding="utf-8")
    (cdi / "gpu.json").write_text(
        json.dumps(
            {
                "cdiVersion": "0.6.0",
                "kind": "vendor.example/gpu",
                "devices": [
                    {
                        "name": "all",
                        "containerEdits": {
                            "env": ["GPU_VISIBLE=all"],
                            "mounts": [
                                {
                                    "hostPath": str(libraries),
                                    "containerPath": "/opt/driver",
                                    "options": ["rbind", "ro"],
                                }
                            ],
                            "deviceNodes": [
                                {"path": "/dev/gpu0", "hostPath": str(device)}
                            ],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(module.stat, "S_ISCHR", lambda mode: True)
    payload = {"process": {"env": ["PATH=/usr/bin"]}, "mounts": []}

    sources = module.apply_cdi_edits(
        payload, ["vendor.example/gpu=all"], [cdi]
    )

    assert sources == [str(cdi / "gpu.json")]
    assert "GPU_VISIBLE=all" in payload["process"]["env"]
    assert {mount["destination"] for mount in payload["mounts"]} == {
        "/opt/driver", "/dev/gpu0"
    }


def test_direct_crun_adapter_rejects_unimplemented_cdi_edits(tmp_path: Path) -> None:
    module = load("oci_runner_crun_rejects_hooks")
    cdi = tmp_path / "cdi"
    cdi.mkdir()
    (cdi / "gpu.json").write_text(
        json.dumps(
            {
                "cdiVersion": "0.6.0",
                "kind": "vendor.example/gpu",
                "devices": [
                    {
                        "name": "all",
                        "containerEdits": {
                            "hooks": [{"hookName": "createContainer", "path": "/hook"}]
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(module.RunnerError, match="unsupported by Cloudmake's direct OCI"):
        module.apply_cdi_edits(
            {"process": {"env": []}, "mounts": []},
            ["vendor.example/gpu=all"],
            [cdi],
        )


def test_direct_crun_profile_is_nonroot_and_preserves_target_status(
    tmp_path: Path, monkeypatch
) -> None:
    module = load("oci_runner_crun_transaction")
    bundle = tmp_path / "bundle"
    rootfs = bundle / "rootfs"
    rootfs.mkdir(parents=True)
    (bundle / "config.json").write_text(
        json.dumps(
            {
                "root": {"path": "rootfs"},
                "process": {"env": ["PATH=/usr/bin"]},
                "linux": {
                    "resources": {},
                    "namespaces": [
                        {"type": "mount"}, {"type": "pid"},
                        {"type": "network"}, {"type": "cgroup"},
                        {"type": "user"},
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    source = tmp_path / "source"
    source.mkdir()
    result = tmp_path / "internal.json"
    observed: dict = {}
    monkeypatch.setattr(module, "chown_workspace", lambda *_: None)

    def fake_run(command, **kwargs):
        if command[:2] == ["crun", "delete"]:
            return subprocess.CompletedProcess(command, 0)
        assert command[:3] == ["crun", "--cgroup-manager=disabled", "run"]
        config = json.loads((Path(kwargs["cwd"]) / "config.json").read_text())
        observed.update(config)
        receipt_mount = next(
            mount for mount in config["mounts"]
            if mount["destination"] == "/run/cloudmake"
        )
        Path(receipt_mount["source"], "result.json").write_text(
            json.dumps({"schema": 1, "exit_code": 2}), encoding="utf-8"
        )
        return subprocess.CompletedProcess(command, 2)

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    exit_code = module.internal_crun_exec(
        [str(bundle), str(source), "65534:65534", str(result), "--", "make", "test"]
    )

    assert exit_code == 2
    assert observed["root"] == {"path": str(rootfs), "readonly": True}
    assert observed["process"]["user"] == {"uid": 65534, "gid": 65534}
    assert observed["process"]["noNewPrivileges"] is True
    assert all(not values for values in observed["process"]["capabilities"].values())
    assert {item["type"] for item in observed["linux"]["namespaces"]} == {"mount"}
    proc = next(item for item in observed["mounts"] if item["destination"] == "/proc")
    assert "rw" in proc["options"]
    assert json.loads(result.read_text())["exit_code"] == 2


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
        "--no-new-privs",
        "--inh-caps=-all",
        "--ambient-caps=-all",
        "--bounding-set=-all",
        "--reuid=65534",
        "--regid=65534",
        "--clear-groups",
    ]
    assert identity == "65534:65534"
    assert (source / "file", 65534, 65534) in ownership
    assert (source, 65534, 65534) in ownership


def test_nonroot_proot_enforces_no_new_privileges(tmp_path: Path, monkeypatch) -> None:
    module = load("oci_runner_nonroot_no_new_privileges")
    source = tmp_path / "source"
    source.mkdir()
    monkeypatch.setattr(module.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(module.os, "getuid", lambda: 1000)
    monkeypatch.setattr(module.os, "getgid", lambda: 100)
    monkeypatch.setattr(module.shutil, "which", lambda name: f"/usr/bin/{name}")

    prefix, identity = module.proot_identity_prefix(source, None)

    assert prefix == ["/usr/bin/setpriv", "--no-new-privs"]
    assert identity == "1000:100"


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
                "error": "crun launch failed",
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
    assert "OCI infrastructure failure: crun launch failed" in completed.stdout
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
