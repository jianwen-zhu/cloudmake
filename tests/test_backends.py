from __future__ import annotations

import base64
import json
import os
import tarfile
from pathlib import Path

import pytest

from conftest import PROJECT_ROOT, run_command, write_executable


LAUNCHER = PROJECT_ROOT / "bin" / "cloudmake"


def engine_dispatch(target: str) -> list[str]:
    encoded = base64.urlsafe_b64encode(target.encode("utf-8")).decode("ascii")
    return [f"REMOTE_TARGET_B64={encoded}", "dispatch"]


def fake_environment(fake_bin: Path, tmp_path: Path) -> dict[str, str]:
    return {
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "FAKE_LOG": str(tmp_path / "provider.jsonl"),
        "FAKE_REMOTE": str(tmp_path / "remote"),
    }


def launcher_environment(fake_bin: Path, tmp_path: Path) -> dict[str, str]:
    environment = fake_environment(fake_bin, tmp_path)
    environment.update(
        {
            "CLOUDMAKE_CONFIG_HOME": str(tmp_path / "config"),
            "CLOUDMAKE_STATE_HOME": str(tmp_path / "state"),
            "CLOUDMAKE_CACHE_HOME": str(tmp_path / "cache"),
        }
    )
    return environment


def external_project(path: Path) -> Path:
    path.mkdir()
    (path / "Makefile").write_text(
        ".PHONY: build test run package benchmark export-release\n"
        "build test run benchmark:\n\t@true\n"
        "release\\ candidate's\\ [gpu]:\n\t@true\n"
        "package:\n\t@mkdir -p $(OUTPUT_DIR)\n\t@printf artifact > $(OUTPUT_DIR)/result\n"
        "export-release:\n\t@mkdir -p dist\n\t@printf artifact > dist/result\n",
        encoding="utf-8",
    )
    (path / "source.txt").write_text("external project\n", encoding="utf-8")
    return path


def test_codespaces_anchor_provides_common_ssh_transport_prerequisites() -> None:
    configuration = json.loads(
        (PROJECT_ROOT / ".devcontainer" / "devcontainer.json").read_text(
            encoding="utf-8"
        )
    )
    dockerfile = (PROJECT_ROOT / ".devcontainer" / "Dockerfile").read_text(
        encoding="utf-8"
    )
    assert "ghcr.io/devcontainers/features/sshd:1" in configuration["features"]
    assert configuration["remoteUser"] == "vscode"
    for command in ("make", "rsync", "tar"):
        assert command in dockerfile


def calls(log: Path, program: str | None = None) -> list[list[str]]:
    if not log.exists():
        return []
    records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    if program is not None:
        records = [record for record in records if record[0] == program]
    return records


def install_fake_colab(fake_bin: Path) -> Path:
    return write_executable(
        fake_bin / "colab",
        r'''#!/usr/bin/env python3
import json
import os
import shutil
import sys
import tarfile
import base64
from pathlib import Path

arguments = sys.argv[1:]
log = Path(os.environ["FAKE_LOG"])
log.parent.mkdir(parents=True, exist_ok=True)
with log.open("a", encoding="utf-8") as stream:
    stream.write(json.dumps(["colab", *arguments]) + "\n")
remote = Path(os.environ["FAKE_REMOTE"])
remote.mkdir(parents=True, exist_ok=True)

def option(name, default="cuda-build"):
    return arguments[arguments.index(name) + 1] if name in arguments else default

command = arguments[0]
session = option("-s")
marker = remote / f"session-{session}"
if command == "version":
    print("fake colab 1.0")
elif command == "sessions":
    if os.environ.get("FAKE_COLAB_AUTH_FAIL"):
        print("Colab authentication expired")
        raise SystemExit(1)
    if marker.exists():
        print(f"[{session}] running")
elif command == "new":
    marker.write_text("running", encoding="utf-8")
elif command == "status":
    print("running" if marker.exists() else "not found")
elif command == "stop":
    marker.unlink(missing_ok=True)
elif command == "upload":
    local, remote_name = arguments[-2:]
    shutil.copyfile(local, remote / Path(remote_name).name)
elif command == "download":
    remote_name, local = arguments[-2:]
    source = remote / Path(remote_name).name
    if not source.exists():
        raise SystemExit(1)
    Path(local).parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, local)
elif command == "exec":
    script = Path(option("-f", ""))
    if (
        (
            os.environ.get("FAKE_COLAB_READINESS_FAIL_ALWAYS")
            or os.environ.get("FAKE_COLAB_READINESS_FAIL_ONCE")
        )
        and script.name == "remote_prerequisites.py"
        and (
            os.environ.get("FAKE_COLAB_READINESS_FAIL_ALWAYS")
            or not (remote / "readiness-failed-once").exists()
        )
    ):
        (remote / "readiness-failed-once").write_text("failed", encoding="utf-8")
        print("Connection was lost.")
        raise SystemExit(1)
    if script.name == "colab_sync.py":
        shutil.copyfile(remote / "cloud-build-source.sha256", remote / "source.sha256")
        shutil.copyfile(remote / "cloud-build-owner.json", remote / ".cloudmake-owner.json")
    elif script.suffix == ".ipynb" and (remote / "cloud-build-target").exists():
        control = (remote / "cloud-build-target").read_text(encoding="utf-8").splitlines()
        target_b64 = control[0]
        target = base64.urlsafe_b64decode(target_b64).decode()
        if len(control) == 5 and control[4]:
            payload = remote / "artifact-payload"
            payload.mkdir(exist_ok=True)
            (payload / "hello").write_text("fake artifact\n", encoding="utf-8")
            with tarfile.open(remote / "artifacts.tar.gz", "w:gz") as archive:
                if os.environ.get("FAKE_MALICIOUS_ARTIFACT"):
                    info = tarfile.TarInfo("../escaped")
                    info.size = 3
                    import io
                    archive.addfile(info, io.BytesIO(b"bad"))
                else:
                    archive.add(payload / "hello", arcname="hello")
elif command == "url":
    print("https://colab.example.invalid/session")
elif command == "ssh":
    pass
else:
    raise SystemExit(f"unsupported fake colab command: {command}")
''',
    )


def install_fake_kaggle(fake_bin: Path) -> Path:
    return write_executable(
        fake_bin / "kaggle",
        r'''#!/usr/bin/env python3
import json
import os
import sys
import tarfile
from pathlib import Path

arguments = sys.argv[1:]
log = Path(os.environ["FAKE_LOG"])
log.parent.mkdir(parents=True, exist_ok=True)
with log.open("a", encoding="utf-8") as stream:
    stream.write(json.dumps(["kaggle", *arguments]) + "\n")

if arguments == ["--version"]:
    print("fake kaggle 1.0")
elif arguments[:2] == ["kernels", "list"]:
    if os.environ.get("FAKE_KAGGLE_AUTH_FAIL"):
        print("Kaggle authentication expired")
        raise SystemExit(1)
    print("ref,title")
elif arguments[:2] == ["kernels", "push"]:
    print("Kernel version submitted")
elif arguments[:2] == ["kernels", "status"]:
    print(os.environ.get("FAKE_KAGGLE_STATUS", "complete"))
elif arguments[:2] == ["kernels", "output"]:
    output = Path(arguments[arguments.index("-p") + 1])
    output.mkdir(parents=True, exist_ok=True)
    pattern = arguments[arguments.index("--file-pattern") + 1]
    if "cloud-build" in pattern:
        (output / "cloud-build.log").write_text("fake kaggle log\n", encoding="utf-8")
    elif "artifacts" in pattern:
        payload = output / "hello"
        payload.write_text("fake artifact\n", encoding="utf-8")
        with tarfile.open(output / "artifacts.tar.gz", "w:gz") as archive:
            archive.add(payload, arcname="hello")
        payload.unlink()
else:
    raise SystemExit(f"unsupported fake kaggle command: {arguments}")
''',
    )


def install_fake_lightning(fake_bin: Path) -> Path:
    return write_executable(
        fake_bin / "lightning",
        r'''#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

arguments = sys.argv[1:]
log = Path(os.environ["FAKE_LOG"])
log.parent.mkdir(parents=True, exist_ok=True)
with log.open("a", encoding="utf-8") as stream:
    stream.write(json.dumps(["lightning", *arguments]) + "\n")
remote = Path(os.environ["FAKE_REMOTE"])
remote.mkdir(parents=True, exist_ok=True)
marker = remote / "lightning-studio"

def option(name, default=""):
    return arguments[arguments.index(name) + 1] if name in arguments else default

if arguments == ["--version"]:
    print("Lightning CLI version 2026.8.18")
elif arguments[:2] == ["auth", "whoami"]:
    if os.environ.get("FAKE_LIGHTNING_AUTH_FAIL"):
        print("No Lightning credentials are available")
        raise SystemExit(1)
    print(json.dumps({"auth_type": "user", "username": "tester"}))
elif arguments[:2] == ["studio", "list"]:
    if os.environ.get("FAKE_LIGHTNING_ACCESS_FAIL"):
        print("Lightning Studio access denied")
        raise SystemExit(1)
    if marker.exists():
        print(json.dumps([json.loads(marker.read_text(encoding="utf-8"))]))
    else:
        print("[]")
elif arguments[:2] == ["studio", "start"]:
    if os.environ.get("FAKE_LIGHTNING_START_FAIL"):
        print("unauthorized")
        raise SystemExit(1)
    marker.write_text(
        json.dumps(
            {"name": option("--name"), "status": "Running", "machine": option("--machine")}
        ),
        encoding="utf-8",
    )
    print(f"Started {option('--name')}")
elif arguments[:2] == ["studio", "switch"]:
    current = json.loads(marker.read_text(encoding="utf-8"))
    current["machine"] = option("--machine")
    marker.write_text(json.dumps(current), encoding="utf-8")
    print(f"Switched {option('--name')} to {option('--machine')}")
elif arguments[:2] == ["studio", "stop"]:
    current = json.loads(marker.read_text(encoding="utf-8"))
    current["status"] = "Stopped"
    marker.write_text(json.dumps(current), encoding="utf-8")
    print(f"Stopped {option('--name')}")
elif arguments[:2] == ["ssh", "generate"]:
    print(f"# ssh s_fake@ssh.lightning.ai")
    print(f"Host {option('--name')}")
    print("  User s_fake")
    print("  Hostname ssh.lightning.ai")
    print("  IdentityFile ~/.ssh/lightning_rsa")
    print("  IdentitiesOnly yes")
else:
    raise SystemExit(f"unsupported fake lightning command: {arguments}")
''',
    )


def install_fake_ssh_tools(fake_bin: Path) -> None:
    write_executable(
        fake_bin / "gh",
        r'''#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path
arguments = sys.argv[1:]
remote = Path(os.environ["FAKE_REMOTE"])
remote.mkdir(parents=True, exist_ok=True)
with Path(os.environ["FAKE_LOG"]).open("a", encoding="utf-8") as stream:
    stream.write(json.dumps(["gh", *arguments]) + "\n")
if arguments[:2] == ["auth", "status"]:
    if os.environ.get("FAKE_GH_AUTH_FAIL"):
        print("GitHub authentication expired")
        raise SystemExit(1)
    print("Logged in")
elif arguments == ["--version"]:
    print("gh version 2.55.0")
elif arguments[:3] == ["codespace", "ssh", "--config"]:
    identity = remote / "codespaces.auto"
    identity.write_text("fake private key", encoding="utf-8")
    Path(f"{identity}.pub").write_text("fake public key", encoding="utf-8")
    print("Host fake-codespace")
    print("    HostName localhost")
    print("    User codespace")
    print(f"    IdentityFile {identity}")
elif arguments[:2] == ["codespace", "view"]:
    print("Available")
elif arguments[:2] == ["codespace", "stop"]:
    print("Stopped")
else:
    raise SystemExit(f"unsupported fake gh command: {arguments}")
''',
    )
    write_executable(
        fake_bin / "ssh",
        r'''#!/usr/bin/env python3
import io
import json
import os
import sys
import tarfile
from pathlib import Path
with Path(os.environ["FAKE_LOG"]).open("a", encoding="utf-8") as stream:
    stream.write(json.dumps(["ssh", *sys.argv[1:]]) + "\n")
joined = " ".join(sys.argv[1:])
if sys.argv[1:] == ["-V"]:
    print("OpenSSH_9.9 test")
if os.environ.get("FAKE_SSH_AUTH_FAIL") and "BatchMode=yes" in joined:
    print("Permission denied")
    raise SystemExit(1)
if os.environ.get("FAKE_REMOTE_MISSING"):
    if "command -v" in joined and os.environ["FAKE_REMOTE_MISSING"] in joined:
        raise SystemExit(1)
if "tar -C" in joined and ".cloudmake-artifacts.tar.gz" in joined:
    remote = Path(os.environ["FAKE_REMOTE"])
    remote.mkdir(parents=True, exist_ok=True)
    with tarfile.open(remote / "ssh-artifacts.tar.gz", "w:gz") as archive:
        if os.environ.get("FAKE_MALICIOUS_ARTIFACT"):
            member = tarfile.TarInfo("../escaped")
            member.size = 3
            archive.addfile(member, io.BytesIO(b"bad"))
        else:
            payload = b"fake ssh artifact\n"
            member = tarfile.TarInfo("hello")
            member.size = len(payload)
            archive.addfile(member, io.BytesIO(payload))
if "printf 'running" in joined:
    print("running")
''',
    )
    write_executable(
        fake_bin / "rsync",
        r'''#!/usr/bin/env python3
import json
import os
import shutil
import sys
from pathlib import Path
with Path(os.environ["FAKE_LOG"]).open("a", encoding="utf-8") as stream:
    stream.write(json.dumps(["rsync", *sys.argv[1:]]) + "\n")
if any(".cloudmake-artifacts.tar.gz" in argument for argument in sys.argv[1:]):
    source = Path(os.environ["FAKE_REMOTE"]) / "ssh-artifacts.tar.gz"
    destination = Path(sys.argv[-1])
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
''',
    )


@pytest.mark.integration
def test_launcher_runs_external_project_through_colab_native(
    fake_bin: Path, tmp_path: Path
) -> None:
    install_fake_colab(fake_bin)
    project = external_project(tmp_path / "external-colab")
    env = launcher_environment(fake_bin, tmp_path)

    run_command(
        [LAUNCHER, "-b", "colab", "release candidate's [gpu]", "SIZE=large"],
        cwd=project,
        env=env,
    )

    remote = Path(env["FAKE_REMOTE"])
    with tarfile.open(remote / "cloud-build-source.tar.gz", "r:gz") as archive:
        names = {name.removeprefix("./") for name in archive.getnames()}
    assert "Makefile" in names
    assert "source.txt" in names
    assert "Makefile.build" not in names
    target_b64, jobs, makefile, encoded, collect = (remote / "cloud-build-target").read_text(
        encoding="utf-8"
    ).splitlines()
    assert (base64.urlsafe_b64decode(target_b64).decode(), makefile) == (
        "release candidate's [gpu]",
        "Makefile",
    )
    assert int(jobs) > 0
    assert json.loads(base64.urlsafe_b64decode(encoded)) == ["SIZE=large"]
    assert collect == ""
    assert not (project / ".cloud-state").exists()
    assert list((tmp_path / "state").rglob("source.tar.gz"))


@pytest.mark.integration
def test_launcher_prepares_external_project_for_kaggle_batch(
    fake_bin: Path, tmp_path: Path
) -> None:
    install_fake_kaggle(fake_bin)
    project = external_project(tmp_path / "external-kaggle")
    env = launcher_environment(fake_bin, tmp_path)
    env["KAGGLE_USERNAME"] = "tester"

    run_command(
        [
            LAUNCHER,
            "-b",
            "kaggle",
            "benchmark",
            "SIZE=large",
        ],
        cwd=project,
        env=env,
    )

    runners = list((tmp_path / "state").rglob("runner.ipynb"))
    assert len(runners) == 1
    serialized = runners[0].read_text(encoding="utf-8")
    assert base64.urlsafe_b64encode(b"benchmark").decode() in serialized
    assert base64.urlsafe_b64encode(b"Makefile").decode() in serialized
    assert base64.urlsafe_b64encode(
        json.dumps(
            ["SIZE=large"], separators=(",", ":")
        ).encode()
    ).decode() in serialized
    assert not (project / ".cloud-state").exists()


@pytest.mark.integration
def test_kaggle_failure_still_downloads_and_prints_the_run_log(
    fake_bin: Path, tmp_path: Path
) -> None:
    install_fake_kaggle(fake_bin)
    project = external_project(tmp_path / "external-kaggle-failure")
    env = launcher_environment(fake_bin, tmp_path)
    env.update(
        {
            "KAGGLE_USERNAME": "tester",
            "KAGGLE_POLL_SECONDS": "0.01",
            "FAKE_KAGGLE_STATUS": "error: compiler unavailable",
        }
    )

    result = run_command(
        [LAUNCHER, "-b", "kaggle", "benchmark"],
        cwd=project,
        env=env,
        check=False,
    )

    assert result.returncode != 0
    assert "fake kaggle log" in result.stdout
    assert any(
        call[1:3] == ["kernels", "output"]
        for call in calls(Path(env["FAKE_LOG"]), "kaggle")
    )


@pytest.mark.integration
def test_launcher_runs_external_project_through_codespaces_ssh(
    fake_bin: Path, tmp_path: Path
) -> None:
    install_fake_ssh_tools(fake_bin)
    project = external_project(tmp_path / "external-ssh")
    env = launcher_environment(fake_bin, tmp_path)
    env["CODESPACE"] = "test-space"

    run_command(
        [
            LAUNCHER,
            "-b",
            "codespaces",
            "benchmark",
            "MESSAGE=hello world",
        ],
        cwd=project,
        env=env,
    )

    all_calls = calls(Path(env["FAKE_LOG"]))
    assert any(
        call[0] == "ssh" and "fake-codespace" in call and call[-1] == "true"
        for call in all_calls
    )
    assert any(call[0] == "rsync" and f"{project}/" in call for call in all_calls)
    rsync_arguments = {
        argument for call in all_calls if call[0] == "rsync" for argument in call[1:]
    }
    assert {"--exclude=/.git/", "--exclude=/.cloud-state/", "--exclude=/artifacts/"} <= rsync_arguments
    assert not any(
        argument in rsync_arguments
        for argument in ("--exclude=/build/", "--exclude=/.venv/", "--exclude=/__pycache__/")
    )
    remote_commands = "\n".join(
        argument
        for call in all_calls
        if call[0] == "ssh"
        for argument in call[1:]
        if "make -C" in argument
    )
    assert "-f Makefile" in remote_commands
    assert "benchmark" in remote_commands
    assert "'MESSAGE=hello world'" in remote_commands
    assert "git clone" not in json.dumps(all_calls)
    assert not (project / ".cloud-state").exists()


@pytest.mark.integration
def test_launcher_runs_external_project_through_user_managed_lab_ssh(
    fake_bin: Path, tmp_path: Path
) -> None:
    install_fake_ssh_tools(fake_bin)
    project = external_project(tmp_path / "external-lab")
    env = launcher_environment(fake_bin, tmp_path)
    env["LAB_HOST"] = "lab-gpu"

    run_command(
        [LAUNCHER, "-b", "lab", "benchmark", "MESSAGE=hello world"],
        cwd=project,
        env=env,
    )

    all_calls = calls(Path(env["FAKE_LOG"]))
    assert any(
        call[0] == "ssh"
        and "-o" in call
        and "BatchMode=yes" in call
        and "lab-gpu" in call
        and call[-1] == "true"
        for call in all_calls
    )
    assert any(call[0] == "rsync" and f"{project}/" in call for call in all_calls)
    assert any(
        call[0] == "rsync"
        and any(
            argument.startswith("lab-gpu:.cloudmake/")
            and argument.endswith("/src/")
            for argument in call[1:]
        )
        for call in all_calls
    )
    assert not any(call[0] in {"colab", "gh", "kaggle", "lightning"} for call in all_calls)
    assert "git clone" not in json.dumps(all_calls)
    assert not list((tmp_path / "state").rglob("ssh_config"))
    assert not (project / ".cloud-state").exists()


@pytest.mark.integration
def test_lab_status_and_stop_preserve_user_managed_lifecycle(
    prototype: Path, fake_bin: Path, tmp_path: Path
) -> None:
    install_fake_ssh_tools(fake_bin)
    env = fake_environment(fake_bin, tmp_path)

    status = run_command(
        ["make", "BACKEND=lab-ssh", "LAB_HOST=lab-gpu", "status"],
        cwd=prototype,
        env=env,
    )
    assert "[cloudmake] status=ready" in status.stdout

    Path(env["FAKE_LOG"]).write_text("", encoding="utf-8")
    stopped = run_command(
        ["make", "BACKEND=lab-ssh", "LAB_HOST=lab-gpu", "stop"],
        cwd=prototype,
        env=env,
    )
    assert "user-managed" in stopped.stdout
    assert calls(Path(env["FAKE_LOG"]), "ssh") == []


@pytest.mark.integration
def test_ssh_collect_fetches_artifacts_transactionally(
    fake_bin: Path, tmp_path: Path
) -> None:
    install_fake_ssh_tools(fake_bin)
    project = external_project(tmp_path / "external-package")
    env = launcher_environment(fake_bin, tmp_path)
    env["CODESPACE"] = "test-space"

    run_command(
        [LAUNCHER, "-b", "codespaces", "--collect", "dist", "export-release"],
        cwd=project,
        env=env,
    )

    assert (project / "artifacts" / "hello").read_text(encoding="utf-8") == (
        "fake ssh artifact\n"
    )
    assert any(
        call[0] == "ssh"
        and any("tar -C" in argument and "/src/dist" in argument for argument in call[1:])
        for call in calls(Path(env["FAKE_LOG"]))
    )
    assert any(
        call[0] == "ssh"
        and any("rm -f" in argument and ".cloudmake-artifacts.tar.gz" in argument for argument in call[1:])
        for call in calls(Path(env["FAKE_LOG"]))
    )
    latest = next((tmp_path / "state" / "projects").glob("*/runs/latest.json"))
    provenance = json.loads(latest.read_text(encoding="utf-8"))
    assert provenance["status"] == "succeeded"
    assert provenance["resource_id"] == "test-space"
    assert len(provenance["source"]["fingerprint"]) == 64
    assert provenance["artifacts"]["files"] == 1
    assert provenance["artifacts"]["total_bytes"] > 0
    assert len(provenance["artifacts"]["fingerprint"]) == 64


@pytest.mark.integration
def test_ssh_collect_rejects_unsafe_artifact_and_preserves_previous_output(
    fake_bin: Path, tmp_path: Path
) -> None:
    install_fake_ssh_tools(fake_bin)
    project = external_project(tmp_path / "external-malicious-package")
    artifacts = project / "artifacts"
    artifacts.mkdir()
    (artifacts / "keep").write_text("keep", encoding="utf-8")
    env = launcher_environment(fake_bin, tmp_path)
    env["CODESPACE"] = "test-space"
    env["FAKE_MALICIOUS_ARTIFACT"] = "1"

    result = run_command(
        [LAUNCHER, "-b", "codespaces", "--collect", "dist", "export-release"],
        cwd=project,
        env=env,
        check=False,
    )

    assert result.returncode != 0
    assert (artifacts / "keep").read_text(encoding="utf-8") == "keep"
    assert not (project.parent / "escaped").exists()


@pytest.mark.integration
def test_colab_native_uploads_changed_source_and_skips_unchanged_archive(
    prototype: Path, fake_bin: Path, tmp_path: Path
) -> None:
    install_fake_colab(fake_bin)
    env = fake_environment(fake_bin, tmp_path)
    log = Path(env["FAKE_LOG"])

    first = run_command(["make", *engine_dispatch("build")], cwd=prototype, env=env)
    assert "Source unchanged" not in first.stdout
    first_calls = calls(log, "colab")
    assert any(call[1] == "new" for call in first_calls)
    assert any(call[1:3] == ["exec", "-s"] and call[-1].endswith("colab_sync.py") for call in first_calls)
    notebook_exec = next(
        call
        for call in first_calls
        if call[1] == "exec" and call[-1].endswith("runner.ipynb")
    )
    assert ".cloud-state/colab-notebook/cuda-build/runner.ipynb" in notebook_exec[-1]
    assert not (prototype / "notebooks" / "colab_output.ipynb").exists()
    assert all(
        call[call.index("--timeout") + 1] == "3600"
        for call in first_calls
        if call[1] == "exec"
    )
    assert any(call[1] == "upload" and call[-1] == "/content/cloud-build-source.tar.gz" for call in first_calls)
    assert not any(call[1] == "ssh" for call in first_calls)

    log.write_text("", encoding="utf-8")
    second = run_command(["make", *engine_dispatch("run")], cwd=prototype, env=env)
    second_calls = calls(log, "colab")
    assert "Source unchanged; skipping archive upload" in second.stdout
    assert not any(call[1] == "new" for call in second_calls)
    assert not any(call[1] == "upload" and call[-1] == "/content/cloud-build-source.tar.gz" for call in second_calls)
    assert any(call[1] == "upload" and call[-1] == "/content/cloud-build-target" for call in second_calls)


@pytest.mark.integration
def test_colab_native_archive_excludes_only_cloudmake_owned_root_paths(
    prototype: Path, fake_bin: Path, tmp_path: Path
) -> None:
    install_fake_colab(fake_bin)
    env = fake_environment(fake_bin, tmp_path)
    for name in (".git", ".cloud-state", "artifacts"):
        directory = prototype / name
        directory.mkdir(exist_ok=True)
        (directory / "excluded.txt").write_text("excluded", encoding="utf-8")
    for name in ("build", ".venv", "__pycache__", ".pytest_cache"):
        directory = prototype / "any-layout" / name
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "included.txt").write_text("included", encoding="utf-8")
    (prototype / "kept.txt").write_text("kept", encoding="utf-8")
    (prototype / "generated_output.ipynb").write_text("included", encoding="utf-8")

    run_command(["make", "sync"], cwd=prototype, env=env)

    archive_path = Path(env["FAKE_REMOTE"]) / "cloud-build-source.tar.gz"
    with tarfile.open(archive_path, "r:gz") as archive:
        names = {name.removeprefix("./") for name in archive.getnames()}
    assert "kept.txt" in names
    assert "generated_output.ipynb" in names
    for name in ("build", ".venv", "__pycache__", ".pytest_cache"):
        assert f"any-layout/{name}/included.txt" in names
    assert not any(
        name.split("/", 1)[0] in {".git", ".cloud-state", "artifacts"}
        for name in names
    )


@pytest.mark.integration
def test_colab_native_collect_fetch_open_and_stop(
    prototype: Path, fake_bin: Path, tmp_path: Path
) -> None:
    install_fake_colab(fake_bin)
    env = fake_environment(fake_bin, tmp_path)

    run_command(
        [
            "make",
            "REMOTE_TARGET=package",
            "REMOTE_COLLECT_DIR_B64=b3V0cHV0",
            "collect",
        ],
        cwd=prototype,
        env=env,
    )
    run_command(["make", "fetch"], cwd=prototype, env=env)
    run_command(["make", "open"], cwd=prototype, env=env)
    run_command(["make", "stop"], cwd=prototype, env=env)

    assert (prototype / "artifacts" / "hello").read_text(encoding="utf-8") == "fake artifact\n"
    colab_calls = calls(Path(env["FAKE_LOG"]), "colab")
    assert sum(
        call[1] == "exec" and call[-1].endswith("remote_prerequisites.py")
        for call in colab_calls
    ) == 3
    assert any(call[1] == "url" and "--open" in call for call in colab_calls)
    assert any(call[1] == "stop" for call in colab_calls)


@pytest.mark.integration
def test_colab_native_reconciles_a_disappeared_session(
    prototype: Path, fake_bin: Path, tmp_path: Path
) -> None:
    install_fake_colab(fake_bin)
    env = fake_environment(fake_bin, tmp_path)
    run_command(["make", *engine_dispatch("build")], cwd=prototype, env=env)
    remote = Path(env["FAKE_REMOTE"])
    (remote / "session-cuda-build").unlink()
    (remote / "source.sha256").unlink()
    (remote / ".cloudmake-owner.json").unlink()
    Path(env["FAKE_LOG"]).write_text("", encoding="utf-8")

    run_command(["make", *engine_dispatch("test")], cwd=prototype, env=env)

    colab_calls = calls(Path(env["FAKE_LOG"]), "colab")
    assert any(call[1] == "new" for call in colab_calls)
    assert any(call[1] == "upload" and call[-1] == "/content/cloud-build-source.tar.gz" for call in colab_calls)


@pytest.mark.integration
def test_colab_native_retries_only_the_non_mutating_readiness_probe(
    prototype: Path, fake_bin: Path, tmp_path: Path
) -> None:
    install_fake_colab(fake_bin)
    env = fake_environment(fake_bin, tmp_path)
    env["FAKE_COLAB_READINESS_FAIL_ONCE"] = "1"

    result = run_command(["make", *engine_dispatch("build")], cwd=prototype, env=env)

    assert "Readiness connection failed" in result.stdout
    colab_calls = calls(Path(env["FAKE_LOG"]), "colab")
    readiness = [
        call
        for call in colab_calls
        if call[1] == "exec" and call[-1].endswith("remote_prerequisites.py")
    ]
    target_runs = [
        call
        for call in colab_calls
        if call[1] == "exec" and call[-1].endswith("runner.ipynb")
    ]
    assert len(readiness) == 2
    assert len(target_runs) == 1


@pytest.mark.integration
def test_colab_native_refuses_to_destroy_an_unreachable_named_session(
    prototype: Path, fake_bin: Path, tmp_path: Path
) -> None:
    install_fake_colab(fake_bin)
    env = fake_environment(fake_bin, tmp_path)
    env["FAKE_COLAB_READINESS_FAIL_ALWAYS"] = "1"

    result = run_command(
        ["make", *engine_dispatch("build")], cwd=prototype, env=env, check=False
    )

    assert result.returncode != 0
    assert "refusing automatic recreation" in result.stdout
    colab_calls = calls(Path(env["FAKE_LOG"]), "colab")
    assert sum(call[1] == "new" for call in colab_calls) == 1
    assert not any(call[1] == "stop" for call in colab_calls)
    assert not any(
        call[1] == "exec" and call[-1].endswith("runner.ipynb")
        for call in colab_calls
    )


@pytest.mark.integration
def test_colab_native_refuses_foreign_workspace_without_explicit_adoption(
    prototype: Path, fake_bin: Path, tmp_path: Path
) -> None:
    install_fake_colab(fake_bin)
    env = fake_environment(fake_bin, tmp_path)
    remote = Path(env["FAKE_REMOTE"])
    remote.mkdir(parents=True, exist_ok=True)
    (remote / ".cloudmake-owner.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "project_id": "foreign",
                "project_name": "other-project",
                "source_path": "/other/project",
                "hostname": "other-host",
            }
        ),
        encoding="utf-8",
    )

    refused = run_command(
        ["make", *engine_dispatch("build")], cwd=prototype, env=env, check=False
    )
    assert refused.returncode != 0
    assert "refusing to replace Colab session" in refused.stdout
    assert not any(
        call[1] == "upload" and call[-1] == "/content/cloud-build-source.tar.gz"
        for call in calls(Path(env["FAKE_LOG"]), "colab")
    )

    adopted = run_command(
        ["make", "CLOUDMAKE_ADOPT=1", *engine_dispatch("build")],
        cwd=prototype,
        env=env,
    )
    assert "Adopting Colab session" in adopted.stdout


@pytest.mark.integration
def test_colab_fetch_rejects_malicious_artifact_and_preserves_existing_output(
    prototype: Path, fake_bin: Path, tmp_path: Path
) -> None:
    install_fake_colab(fake_bin)
    env = fake_environment(fake_bin, tmp_path)
    env["FAKE_MALICIOUS_ARTIFACT"] = "1"
    artifacts = prototype / "artifacts"
    artifacts.mkdir()
    (artifacts / "keep").write_text("keep", encoding="utf-8")

    result = run_command(
        [
            "make",
            "REMOTE_TARGET=package",
            "REMOTE_COLLECT_DIR_B64=b3V0cHV0",
            "collect",
        ],
        cwd=prototype,
        env=env,
        check=False,
    )

    assert result.returncode != 0
    assert (artifacts / "keep").read_text(encoding="utf-8") == "keep"
    assert not (prototype.parent / "escaped").exists()


@pytest.mark.integration
def test_kaggle_submits_every_target_but_reuses_local_snapshot(
    prototype: Path, fake_bin: Path, tmp_path: Path
) -> None:
    install_fake_kaggle(fake_bin)
    env = fake_environment(fake_bin, tmp_path)
    common = ["make", "BACKEND=kaggle-notebook", "KAGGLE_USERNAME=tester", "KAGGLE_POLL_SECONDS=0.01"]

    first = run_command([*common, *engine_dispatch("build")], cwd=prototype, env=env)
    assert "Refreshed cached source archive" in first.stdout
    second = run_command([*common, *engine_dispatch("test")], cwd=prototype, env=env)
    assert "Source unchanged; reusing cached source archive" in second.stdout

    kaggle_calls = calls(Path(env["FAKE_LOG"]), "kaggle")
    assert sum(call[1:3] == ["kernels", "push"] for call in kaggle_calls) == 2
    metadata = json.loads(
        (prototype / ".cloud-state" / "kaggle-notebook" / "cloud-build-prototype" / "kernel" / "kernel-metadata.json").read_text(encoding="utf-8")
    )
    assert metadata["is_private"] is True
    assert metadata["enable_internet"] is False


@pytest.mark.integration
def test_kaggle_collect_and_fetch_return_artifact(
    prototype: Path, fake_bin: Path, tmp_path: Path
) -> None:
    install_fake_kaggle(fake_bin)
    env = fake_environment(fake_bin, tmp_path)
    common = ["make", "BACKEND=kaggle-notebook", "KAGGLE_USERNAME=tester", "KAGGLE_POLL_SECONDS=0.01"]
    run_command(
        [
            *common,
            "REMOTE_TARGET=package",
            "REMOTE_COLLECT_DIR_B64=b3V0cHV0",
            "collect",
        ],
        cwd=prototype,
        env=env,
    )
    run_command([*common, "fetch"], cwd=prototype, env=env)
    assert (prototype / "artifacts" / "hello").read_text(encoding="utf-8") == "fake artifact\n"


@pytest.mark.integration
def test_codespaces_uses_anchor_only_for_ssh_and_never_clones_project(
    prototype: Path, fake_bin: Path, tmp_path: Path
) -> None:
    install_fake_ssh_tools(fake_bin)
    env = fake_environment(fake_bin, tmp_path)

    run_command(
        [
            "make",
            "BACKEND=codespaces-ssh",
            "CODESPACE=test-space",
            *engine_dispatch("build"),
        ],
        cwd=prototype,
        env=env,
    )
    run_command(
        ["make", "BACKEND=codespaces-ssh", "CODESPACE=test-space", "stop"],
        cwd=prototype,
        env=env,
    )

    all_calls = calls(Path(env["FAKE_LOG"]))
    serialized = json.dumps(all_calls)
    assert ["gh", "codespace", "ssh", "--config", "-c", "test-space"] in all_calls
    assert "git clone" not in serialized
    assert "git push" not in serialized
    assert "/workspaces/.cloudmake/cloud-build-prototype/src" in serialized
    assert any(call[0] == "rsync" and f"{prototype}/" in call for call in all_calls)
    assert ["gh", "codespace", "stop", "-c", "test-space"] in all_calls


@pytest.mark.integration
def test_colab_ssh_builds_proxy_configuration_and_uses_common_transport(
    prototype: Path, fake_bin: Path, tmp_path: Path
) -> None:
    install_fake_colab(fake_bin)
    install_fake_ssh_tools(fake_bin)
    env = fake_environment(fake_bin, tmp_path)
    identity = tmp_path / "id_ed25519"
    identity.write_text("fake private key used only as a path", encoding="utf-8")

    run_command(
        [
            "make",
            "BACKEND=colab-ssh",
            f"COLAB_IDENTITY={identity}",
            *engine_dispatch("build"),
        ],
        cwd=prototype,
        env=env,
    )
    config = prototype / ".cloud-state" / "colab-ssh" / "cuda-build" / "ssh_config"
    content = config.read_text(encoding="utf-8")
    assert "Host colab.cuda-build" in content
    assert "ssh --proxy-mode" in content
    assert str(identity) in content

    all_calls = calls(Path(env["FAKE_LOG"]))
    serialized = json.dumps(all_calls)
    assert "/content/.cloudmake/cloud-build-prototype/src" in serialized
    assert any(call[0] == "rsync" for call in all_calls)


@pytest.mark.integration
def test_lightning_studio_uses_persistent_ssh_transport_without_git(
    prototype: Path, fake_bin: Path, tmp_path: Path
) -> None:
    install_fake_lightning(fake_bin)
    install_fake_ssh_tools(fake_bin)
    env = fake_environment(fake_bin, tmp_path)
    identity = tmp_path / "lightning_rsa"
    identity.write_text("fake provider-owned private key", encoding="utf-8")
    Path(f"{identity}.pub").write_text("fake public key", encoding="utf-8")
    common = [
        "make",
        "BACKEND=lightning-studio-ssh",
        "LIGHTNING_STUDIO=test-studio",
        "LIGHTNING_TEAMSPACE=tester/general",
        "LIGHTNING_MACHINE=T4",
        f"LIGHTNING_IDENTITY={identity}",
    ]

    run_command([*common, *engine_dispatch("build")], cwd=prototype, env=env)
    switched = [
        value if value != "LIGHTNING_MACHINE=T4" else "LIGHTNING_MACHINE=L4"
        for value in common
    ]
    run_command([*switched, *engine_dispatch("build")], cwd=prototype, env=env)
    run_command([*common, "stop"], cwd=prototype, env=env)

    config = (
        prototype
        / ".cloud-state"
        / "lightning-studio-ssh"
        / "tester--general--test-studio"
        / "ssh_config"
    )
    contents = config.read_text(encoding="utf-8")
    assert "Host test-studio" in contents
    assert "Hostname ssh.lightning.ai" in contents
    assert str(identity) in contents
    assert "~/.ssh/lightning_rsa" not in contents
    generated_state = config.parent
    assert "fake provider-owned private key" not in "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in generated_state.rglob("*")
        if path.is_file()
    )

    all_calls = calls(Path(env["FAKE_LOG"]))
    serialized = json.dumps(all_calls)
    assert [
        "lightning",
        "studio",
        "start",
        "--name",
        "test-studio",
        "--teamspace",
        "tester/general",
        "--machine",
        "T4",
        "--create",
    ] in all_calls
    assert [
        "lightning",
        "studio",
        "switch",
        "--name",
        "test-studio",
        "--teamspace",
        "tester/general",
        "--machine",
        "L4",
    ] in all_calls
    assert [
        "lightning",
        "studio",
        "stop",
        "--name",
        "test-studio",
        "--teamspace",
        "tester/general",
    ] in all_calls
    assert (
        "/teamspace/studios/this_studio/.cloudmake/cloud-build-prototype/src"
        in serialized
    )
    assert "git clone" not in serialized
    assert "git push" not in serialized


def test_unknown_backend_fails_before_provider_execution(prototype: Path) -> None:
    result = run_command(
        ["make", "BACKEND=does-not-exist", *engine_dispatch("build")],
        cwd=prototype,
        check=False,
    )
    assert result.returncode != 0
    assert 'Unknown backend "does-not-exist"' in result.stdout


def test_help_keeps_notebook_and_ssh_names_distinct(prototype: Path) -> None:
    result = run_command(["make", "help"], cwd=prototype)
    assert "colab-notebook" in result.stdout
    assert "kaggle-notebook" in result.stdout
    assert "colab-ssh" in result.stdout
    assert "codespaces-ssh" in result.stdout
    assert "lab-ssh" in result.stdout
    assert "lightning-studio-ssh" in result.stdout


@pytest.mark.parametrize(
    "backend",
    [
        "colab-notebook",
        "kaggle-notebook",
        "codespaces-ssh",
        "colab-ssh",
        "lab-ssh",
        "lightning-studio-ssh",
    ],
)
@pytest.mark.parametrize("project_target", ["build", "test", "run"])
def test_engine_defines_no_project_target_shortcuts(
    prototype: Path, backend: str, project_target: str
) -> None:
    result = run_command(
        ["make", f"BACKEND={backend}", project_target],
        cwd=prototype,
        check=False,
    )

    assert result.returncode == 2
    assert "No rule to make target" in result.stdout
    assert project_target in result.stdout


@pytest.mark.parametrize(
    ("backend", "lifecycle", "capability"),
    [
        ("colab-notebook", "session", "incremental-sync"),
        ("kaggle-notebook", "batch", "batch"),
        ("codespaces-ssh", "session", "shell"),
        ("colab-ssh", "session", "gpu"),
        ("lab-ssh", "session", "incremental-sync"),
        ("lightning-studio-ssh", "session", "persistent-storage"),
    ],
)
def test_backend_contract_declares_lifecycle_and_capabilities(
    prototype: Path, backend: str, lifecycle: str, capability: str
) -> None:
    result = run_command(["make", f"BACKEND={backend}", "backend-info"], cwd=prototype)
    assert "api=1" in result.stdout
    assert f"lifecycle={lifecycle}" in result.stdout
    assert capability in result.stdout


@pytest.mark.integration
def test_ssh_remote_prerequisite_failure_blocks_sync(
    prototype: Path, fake_bin: Path, tmp_path: Path
) -> None:
    install_fake_ssh_tools(fake_bin)
    env = fake_environment(fake_bin, tmp_path)
    env["FAKE_REMOTE_MISSING"] = "make"

    result = run_command(
        [
            "make",
            "BACKEND=codespaces-ssh",
            "CODESPACE=test-space",
            *engine_dispatch("build"),
        ],
        cwd=prototype,
        env=env,
        check=False,
    )
    assert result.returncode != 0
    assert "Missing required remote command: make" in result.stdout
    assert calls(Path(env["FAKE_LOG"]), "rsync") == []


@pytest.mark.parametrize(
    ("backend", "override", "missing"),
    [
        ("colab-notebook", "COLAB_BIN=missing-colab-for-test", "missing-colab-for-test"),
        ("kaggle-notebook", "KAGGLE_BIN=missing-kaggle-for-test", "missing-kaggle-for-test"),
        ("codespaces-ssh", "GH_BIN=missing-gh-for-test", "missing-gh-for-test"),
        ("colab-ssh", "COLAB_BIN=missing-colab-for-test", "missing-colab-for-test"),
        ("lab-ssh", "SSH_BIN=missing-ssh-for-test", "missing-ssh-for-test"),
        ("lightning-studio-ssh", "LIGHTNING_BIN=missing-lightning-for-test", "missing-lightning-for-test"),
    ],
)
def test_prerequisites_reports_missing_backend_command(
    prototype: Path, backend: str, override: str, missing: str
) -> None:
    result = run_command(
        ["make", f"BACKEND={backend}", override, "prerequisites"],
        cwd=prototype,
        check=False,
    )

    assert result.returncode == 2
    assert f"Missing required command: {missing}" in result.stdout
    assert "README" in result.stdout


@pytest.mark.parametrize(
    ("backend", "arguments", "expected"),
    [
        ("kaggle-notebook", [], "KAGGLE_USERNAME"),
        ("codespaces-ssh", [], "CODESPACE"),
        ("colab-ssh", ["COLAB_IDENTITY=/does/not/exist"], "COLAB_IDENTITY"),
        ("lab-ssh", [], "LAB_HOST"),
        (
            "lightning-studio-ssh",
            [
                "LIGHTNING_STUDIO=test-studio",
                "LIGHTNING_TEAMSPACE=tester/general",
                "LIGHTNING_IDENTITY=/does/not/exist",
            ],
            "LIGHTNING_IDENTITY",
        ),
    ],
)
def test_prerequisites_reports_missing_backend_setting(
    prototype: Path,
    fake_bin: Path,
    tmp_path: Path,
    backend: str,
    arguments: list[str],
    expected: str,
) -> None:
    install_fake_colab(fake_bin)
    install_fake_kaggle(fake_bin)
    install_fake_lightning(fake_bin)
    install_fake_ssh_tools(fake_bin)
    env = fake_environment(fake_bin, tmp_path)

    result = run_command(
        ["make", f"BACKEND={backend}", *arguments, "prerequisites"],
        cwd=prototype,
        env=env,
        check=False,
    )

    assert result.returncode == 2
    assert expected in result.stdout


def test_lab_prerequisites_requires_a_simple_openssh_alias(
    prototype: Path, fake_bin: Path, tmp_path: Path
) -> None:
    install_fake_ssh_tools(fake_bin)
    env = fake_environment(fake_bin, tmp_path)

    result = run_command(
        [
            "make",
            "BACKEND=lab-ssh",
            "LAB_HOST=researcher@lab.example --bad-option",
            "prerequisites",
        ],
        cwd=prototype,
        env=env,
        check=False,
    )

    assert result.returncode == 2
    assert "LAB_HOST must be a simple OpenSSH Host alias" in result.stdout
    assert calls(Path(env["FAKE_LOG"]), "ssh") == []


@pytest.mark.parametrize(
    ("setting", "expected"),
    [
        ("KAGGLE_TIMEOUT=0", "KAGGLE_TIMEOUT must be a positive number"),
        ("KAGGLE_POLL_SECONDS=soon", "KAGGLE_POLL_SECONDS must be a positive number"),
    ],
)
def test_kaggle_prerequisites_reject_invalid_timing_settings(
    prototype: Path,
    fake_bin: Path,
    tmp_path: Path,
    setting: str,
    expected: str,
) -> None:
    install_fake_kaggle(fake_bin)
    env = fake_environment(fake_bin, tmp_path)

    result = run_command(
        [
            "make",
            "BACKEND=kaggle-notebook",
            "KAGGLE_USERNAME=tester",
            setting,
            "prerequisites",
        ],
        cwd=prototype,
        env=env,
        check=False,
    )

    assert result.returncode == 2
    assert expected in result.stdout


@pytest.mark.integration
@pytest.mark.parametrize(
    ("backend", "arguments", "expected_program"),
    [
        ("colab-notebook", [], "colab"),
        ("kaggle-notebook", ["KAGGLE_USERNAME=tester"], "kaggle"),
        ("codespaces-ssh", ["CODESPACE=test-space"], "gh"),
        ("lab-ssh", ["LAB_HOST=lab-gpu"], "ssh"),
    ],
)
def test_doctor_performs_read_only_provider_probe(
    prototype: Path,
    fake_bin: Path,
    tmp_path: Path,
    backend: str,
    arguments: list[str],
    expected_program: str,
) -> None:
    install_fake_colab(fake_bin)
    install_fake_kaggle(fake_bin)
    install_fake_ssh_tools(fake_bin)
    env = fake_environment(fake_bin, tmp_path)

    result = run_command(
        ["make", f"BACKEND={backend}", *arguments, "doctor"],
        cwd=prototype,
        env=env,
    )

    assert f"Backend {backend} is ready" in result.stdout
    provider_calls = calls(Path(env["FAKE_LOG"]), expected_program)
    assert provider_calls
    serialized = json.dumps(provider_calls)
    assert '"new"' not in serialized
    assert '"push"' not in serialized
    assert '"stop"' not in serialized
    assert '"ssh", "--config"' not in serialized


@pytest.mark.integration
def test_colab_ssh_doctor_checks_client_and_key_without_opening_ssh(
    prototype: Path, fake_bin: Path, tmp_path: Path
) -> None:
    install_fake_colab(fake_bin)
    install_fake_ssh_tools(fake_bin)
    env = fake_environment(fake_bin, tmp_path)
    identity = tmp_path / "id_ed25519"
    identity.write_text("test-only key path", encoding="utf-8")

    result = run_command(
        [
            "make",
            "BACKEND=colab-ssh",
            f"COLAB_IDENTITY={identity}",
            "doctor",
        ],
        cwd=prototype,
        env=env,
    )

    assert "Backend colab-ssh is ready" in result.stdout
    assert calls(Path(env["FAKE_LOG"]), "colab")
    assert calls(Path(env["FAKE_LOG"]), "ssh") == []
    assert not (prototype / ".cloud-state" / "colab-ssh").exists()


@pytest.mark.integration
def test_lightning_doctor_is_read_only_and_keeps_credentials_provider_owned(
    prototype: Path, fake_bin: Path, tmp_path: Path
) -> None:
    install_fake_lightning(fake_bin)
    install_fake_ssh_tools(fake_bin)
    env = fake_environment(fake_bin, tmp_path)
    identity = tmp_path / "lightning_rsa"
    identity.write_text("test-only provider key path", encoding="utf-8")

    result = run_command(
        [
            "make",
            "BACKEND=lightning-studio-ssh",
            "LIGHTNING_STUDIO=test-studio",
            "LIGHTNING_TEAMSPACE=tester/general",
            f"LIGHTNING_IDENTITY={identity}",
            "doctor",
        ],
        cwd=prototype,
        env=env,
    )

    assert "Backend lightning-studio-ssh is ready" in result.stdout
    provider_calls = calls(Path(env["FAKE_LOG"]), "lightning")
    assert ["lightning", "auth", "whoami", "--json"] in provider_calls
    assert [
        "lightning",
        "studio",
        "list",
        "--teamspace",
        "tester/general",
        "--json",
    ] in provider_calls
    serialized = json.dumps(provider_calls)
    assert '"start"' not in serialized
    assert '"ssh", "generate"' not in serialized
    assert not (prototype / ".cloud-state" / "lightning-studio-ssh").exists()


@pytest.mark.integration
def test_lightning_allocation_failure_stops_before_ssh_or_sync(
    prototype: Path, fake_bin: Path, tmp_path: Path
) -> None:
    install_fake_lightning(fake_bin)
    install_fake_ssh_tools(fake_bin)
    env = fake_environment(fake_bin, tmp_path)
    env["FAKE_LIGHTNING_START_FAIL"] = "1"
    identity = tmp_path / "lightning_rsa"
    identity.write_text("test-only provider key path", encoding="utf-8")

    result = run_command(
        [
            "make",
            "BACKEND=lightning-studio-ssh",
            "LIGHTNING_STUDIO=test-studio",
            "LIGHTNING_TEAMSPACE=tester/general",
            f"LIGHTNING_IDENTITY={identity}",
            *engine_dispatch("build"),
        ],
        cwd=prototype,
        env=env,
        check=False,
    )

    assert result.returncode != 0
    assert "unauthorized" in result.stdout
    all_calls = calls(Path(env["FAKE_LOG"]))
    assert not any(call[:3] == ["lightning", "ssh", "generate"] for call in all_calls)
    assert calls(Path(env["FAKE_LOG"]), "rsync") == []


def test_help_is_available_when_backend_dependency_is_missing(prototype: Path) -> None:
    result = run_command(
        ["make", "BACKEND=colab-notebook", "COLAB_BIN=missing-colab-for-test", "help"],
        cwd=prototype,
    )
    assert "Targets:" in result.stdout
    assert "doctor" in result.stdout


def test_operational_target_is_gated_before_missing_provider_is_executed(
    prototype: Path,
) -> None:
    result = run_command(
        [
            "make",
            "BACKEND=colab-notebook",
            "COLAB_BIN=missing-colab-for-test",
            *engine_dispatch("build"),
        ],
        cwd=prototype,
        check=False,
    )
    assert result.returncode == 2
    assert "Missing required command: missing-colab-for-test" in result.stdout
    assert "missing-colab-for-test: command not found" not in result.stdout


@pytest.mark.integration
@pytest.mark.parametrize(
    ("backend", "arguments", "failure_variable", "forbidden_fragment"),
    [
        ("colab-notebook", [], "FAKE_COLAB_AUTH_FAIL", '"new"'),
        ("kaggle-notebook", ["KAGGLE_USERNAME=tester"], "FAKE_KAGGLE_AUTH_FAIL", '"push"'),
        ("codespaces-ssh", ["CODESPACE=test-space"], "FAKE_GH_AUTH_FAIL", '"ssh", "--config"'),
        ("lab-ssh", ["LAB_HOST=lab-gpu"], "FAKE_SSH_AUTH_FAIL", '"rsync"'),
    ],
)
def test_authentication_failure_blocks_provider_operation(
    prototype: Path,
    fake_bin: Path,
    tmp_path: Path,
    backend: str,
    arguments: list[str],
    failure_variable: str,
    forbidden_fragment: str,
) -> None:
    install_fake_colab(fake_bin)
    install_fake_kaggle(fake_bin)
    install_fake_ssh_tools(fake_bin)
    env = fake_environment(fake_bin, tmp_path)
    env[failure_variable] = "1"

    result = run_command(
        ["make", f"BACKEND={backend}", *arguments, *engine_dispatch("build")],
        cwd=prototype,
        env=env,
        check=False,
    )

    assert result.returncode == 2
    assert "authentication or access probe failed" in result.stdout
    assert forbidden_fragment not in json.dumps(calls(Path(env["FAKE_LOG"])))


def test_prerequisites_enforces_minimum_python_version(
    prototype: Path, fake_bin: Path, tmp_path: Path
) -> None:
    install_fake_colab(fake_bin)
    old_python = write_executable(
        fake_bin / "old-python",
        "#!/bin/sh\nexit 1\n",
    )
    env = fake_environment(fake_bin, tmp_path)

    result = run_command(
        [
            "make",
            "BACKEND=colab-notebook",
            f"PYTHON_BIN={old_python.name}",
            "prerequisites",
        ],
        cwd=prototype,
        env=env,
        check=False,
    )

    assert result.returncode == 2
    assert "Python 3.9 or newer is required" in result.stdout
