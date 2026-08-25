from __future__ import annotations

import base64
import io
import json
import os
import shlex
import stat
import subprocess
import sys
import tarfile
import time
from pathlib import Path

import pytest

from conftest import PROJECT_ROOT, run_command


IDENTITY = PROJECT_ROOT / "tools" / "project_identity.py"
LOCK = PROJECT_ROOT / "tools" / "with_lock.py"
SAFE_EXTRACT = PROJECT_ROOT / "tools" / "safe_extract.py"
REMOTE_LOCK = PROJECT_ROOT / "tools" / "remote_lock.sh"
FINGERPRINT = PROJECT_ROOT / "tools" / "source_fingerprint.py"
REMOTE_PREREQUISITES = PROJECT_ROOT / "tools" / "remote_prerequisites.py"
NORMALIZE_STATUS = PROJECT_ROOT / "tools" / "normalize_status.py"
REMOTE_MAKE_COMMAND = PROJECT_ROOT / "tools" / "remote_make_command.py"
REMOTE_COLLECT_COMMAND = PROJECT_ROOT / "tools" / "remote_collect_command.py"
VALIDATE_SSH_CONFIG = PROJECT_ROOT / "tools" / "validate_ssh_config.py"


def ensure_identity(project: Path, state: Path, name: str = "sample") -> Path:
    run_command(
        [
            sys.executable,
            IDENTITY,
            "ensure",
            "--state-dir",
            state,
            "--project-root",
            project,
            "--project-name",
            name,
        ],
        cwd=project,
    )
    return state / "owner.json"


def test_project_identity_is_stable_atomic_and_private(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    state = tmp_path / "state"
    owner = ensure_identity(project, state)
    first = owner.read_bytes()
    ensure_identity(project, state)

    assert owner.read_bytes() == first
    assert stat.S_IMODE(owner.stat().st_mode) == 0o600
    value = json.loads(first)
    assert value["schema"] == 1
    assert value["source_path"] == str(project.resolve())
    assert len(value["project_id"]) == 24
    assert not list(state.glob("*.tmp"))


def test_project_identity_refuses_mismatch_and_allows_explicit_adoption(
    tmp_path: Path,
) -> None:
    first_project = tmp_path / "first"
    second_project = tmp_path / "second"
    first_project.mkdir()
    second_project.mkdir()
    expected = ensure_identity(first_project, tmp_path / "first-state")
    actual = ensure_identity(second_project, tmp_path / "second-state")

    refused = run_command(
        [
            sys.executable,
            IDENTITY,
            "check",
            "--expected",
            expected,
            "--actual",
            actual,
            "--resource",
            "test workspace",
        ],
        cwd=tmp_path,
        check=False,
    )
    assert refused.returncode == 73
    assert "refusing to replace test workspace" in refused.stdout
    assert "CLOUDMAKE_ADOPT=1" in refused.stdout

    adopted = run_command(
        [
            sys.executable,
            IDENTITY,
            "check",
            "--expected",
            expected,
            "--actual",
            actual,
            "--resource",
            "test workspace",
            "--adopt",
        ],
        cwd=tmp_path,
    )
    assert "Adopting test workspace" in adopted.stdout


def test_corrupt_identity_is_not_silently_replaced(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    state = tmp_path / "state"
    state.mkdir()
    owner = state / "owner.json"
    owner.write_text("{broken", encoding="utf-8")

    result = run_command(
        [
            sys.executable,
            IDENTITY,
            "ensure",
            "--state-dir",
            state,
            "--project-root",
            project,
            "--project-name",
            "sample",
        ],
        cwd=tmp_path,
        check=False,
    )
    assert result.returncode == 73
    assert "corrupt" in result.stdout
    assert owner.read_text(encoding="utf-8") == "{broken"


def test_local_lock_serializes_processes_and_recovers_after_exit(tmp_path: Path) -> None:
    lock_path = tmp_path / "operation.lock"
    ready = tmp_path / "ready"
    holder = subprocess.Popen(
        [
            sys.executable,
            os.fspath(LOCK),
            "--path",
            os.fspath(lock_path),
            "--timeout",
            "1",
            "--",
            sys.executable,
            "-c",
            (
                "from pathlib import Path; import time; "
                f"Path({str(ready)!r}).write_text('ready'); time.sleep(0.6)"
            ),
        ],
        cwd=tmp_path,
    )
    try:
        deadline = time.monotonic() + 2
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.exists()

        blocked = run_command(
            [
                sys.executable,
                LOCK,
                "--path",
                lock_path,
                "--timeout",
                "0.05",
                "--",
                sys.executable,
                "-c",
                "raise SystemExit(0)",
            ],
            cwd=tmp_path,
            check=False,
        )
        assert blocked.returncode == 75
        assert "timed out waiting" in blocked.stdout
        assert "pid" in blocked.stdout
    finally:
        holder.wait(timeout=3)

    recovered = run_command(
        [
            sys.executable,
            LOCK,
            "--path",
            lock_path,
            "--timeout",
            "0.2",
            "--",
            sys.executable,
            "-c",
            "raise SystemExit(0)",
        ],
        cwd=tmp_path,
    )
    assert recovered.returncode == 0


def write_tar(path: Path, members: list[tuple[tarfile.TarInfo, bytes]]) -> None:
    with tarfile.open(path, "w:gz") as archive:
        for info, payload in members:
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))


def test_safe_extract_replaces_artifacts_atomically(tmp_path: Path) -> None:
    destination = tmp_path / "artifacts"
    destination.mkdir()
    (destination / "old").write_text("old", encoding="utf-8")
    archive = tmp_path / "artifacts.tar.gz"
    member = tarfile.TarInfo("result/output.txt")
    write_tar(archive, [(member, b"new")])

    run_command(
        [
            sys.executable,
            SAFE_EXTRACT,
            "--archive",
            archive,
            "--destination",
            destination,
        ],
        cwd=tmp_path,
    )
    assert not (destination / "old").exists()
    assert (destination / "result" / "output.txt").read_text(encoding="utf-8") == "new"


@pytest.mark.parametrize("name", ["../escape", "/absolute/escape"])
def test_safe_extract_rejects_unsafe_paths_without_touching_existing_output(
    tmp_path: Path, name: str
) -> None:
    destination = tmp_path / "artifacts"
    destination.mkdir()
    (destination / "keep").write_text("keep", encoding="utf-8")
    archive = tmp_path / "bad.tar.gz"
    write_tar(archive, [(tarfile.TarInfo(name), b"bad")])

    result = run_command(
        [
            sys.executable,
            SAFE_EXTRACT,
            "--archive",
            archive,
            "--destination",
            destination,
        ],
        cwd=tmp_path,
        check=False,
    )
    assert result.returncode != 0
    assert (destination / "keep").read_text(encoding="utf-8") == "keep"
    assert not (tmp_path / "escape").exists()


def test_safe_extract_rejects_links(tmp_path: Path) -> None:
    archive = tmp_path / "link.tar.gz"
    link = tarfile.TarInfo("link")
    link.type = tarfile.SYMTYPE
    link.linkname = "../outside"
    write_tar(archive, [(link, b"")])
    result = run_command(
        [
            sys.executable,
            SAFE_EXTRACT,
            "--archive",
            archive,
            "--destination",
            tmp_path / "artifacts",
        ],
        cwd=tmp_path,
        check=False,
    )
    assert result.returncode != 0
    assert "links are not accepted" in result.stdout


def remote_lock(operation: str, directory: Path, token: str, stale: int = 3600):
    return run_command(
        ["sh", REMOTE_LOCK, operation, directory, token, str(stale)],
        cwd=directory.parent,
        check=False,
    )


def test_remote_lock_has_token_safe_release_and_stale_recovery(tmp_path: Path) -> None:
    directory = tmp_path / "workspace.lock"
    assert remote_lock("acquire", directory, "one").returncode == 0
    assert remote_lock("acquire", directory, "two").returncode == 75
    assert remote_lock("release", directory, "wrong").returncode == 0
    assert directory.exists()
    assert remote_lock("release", directory, "one").returncode == 0
    assert not directory.exists()

    assert remote_lock("acquire", directory, "old").returncode == 0
    (directory / "started").write_text("1\n", encoding="utf-8")
    recovered = remote_lock("acquire", directory, "new", stale=1)
    assert recovered.returncode == 0
    assert "stale" in recovered.stdout
    assert (directory / "token").read_text(encoding="utf-8").strip() == "new"


def test_manifest_archive_ignore_and_dry_run_share_one_selection(tmp_path: Path) -> None:
    (tmp_path / "keep.txt").write_text("one", encoding="utf-8")
    (tmp_path / "remove.txt").write_text("remove", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("secret", encoding="utf-8")
    (tmp_path / "cache").mkdir()
    (tmp_path / "cache" / "value").write_text("cache", encoding="utf-8")
    (tmp_path / ".cloudmakeignore").write_text("secret.txt\ncache/\n", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    archive = tmp_path / "source.tar.gz"

    run_command(
        [
            sys.executable,
            FINGERPRINT,
            "--manifest",
            manifest,
            "--archive",
            archive,
        ],
        cwd=tmp_path,
    )
    with tarfile.open(archive, "r:gz") as source:
        names = set(source.getnames())
    assert "keep.txt" in names
    assert ".cloudmakeignore" in names
    assert "secret.txt" not in names
    assert not any(name.startswith("cache") for name in names)

    (tmp_path / "keep.txt").write_text("two", encoding="utf-8")
    (tmp_path / "added.txt").write_text("added", encoding="utf-8")
    (tmp_path / "remove.txt").unlink()
    plan = run_command(
        [
            sys.executable,
            FINGERPRINT,
            "--compare",
            manifest,
            "--dry-run",
        ],
        cwd=tmp_path,
    )
    assert "M keep.txt" in plan.stdout
    assert "A added.txt" in plan.stdout
    assert "D remove.txt" in plan.stdout
    assert "Source plan:" in plan.stdout


def test_source_size_limit_fails_before_archive_creation(tmp_path: Path) -> None:
    (tmp_path / "large.bin").write_bytes(b"x" * 2048)
    archive = tmp_path / "source.tar.gz"
    result = run_command(
        [
            sys.executable,
            FINGERPRINT,
            "--archive",
            archive,
            "--max-mb",
            "0.001",
        ],
        cwd=tmp_path,
        check=False,
    )
    assert result.returncode == 2
    assert "above the configured" in result.stdout
    assert not archive.exists()


def test_source_snapshot_rejects_symlink_outside_project(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.write_text("outside", encoding="utf-8")
    (tmp_path / "outside-link").symlink_to(outside)
    result = run_command(
        [sys.executable, FINGERPRINT], cwd=tmp_path, check=False
    )
    assert result.returncode != 0
    assert "source symlink escapes the project" in result.stdout


def test_make_sync_dry_run_does_not_require_or_contact_provider(prototype: Path) -> None:
    result = run_command(
        [
            "make",
            "BACKEND=colab-notebook",
            "COLAB_BIN=definitely-missing-colab",
            "sync-dry-run",
        ],
        cwd=prototype,
    )
    assert "Source plan:" in result.stdout
    assert "Missing required command: definitely-missing-colab" not in result.stdout


def test_remote_prerequisite_probe_reports_missing_tools(tmp_path: Path) -> None:
    empty_path = tmp_path / "empty-path"
    empty_path.mkdir()
    result = run_command(
        [sys.executable, REMOTE_PREREQUISITES],
        cwd=tmp_path,
        env={"PATH": str(empty_path)},
        check=False,
    )
    assert result.returncode == 2
    assert "make" in result.stdout
    assert "tar" in result.stdout


def test_codespaces_ssh_config_requires_complete_key_pair(tmp_path: Path) -> None:
    identity = tmp_path / "codespaces.auto"
    config = tmp_path / "ssh_config"
    config.write_text(
        f"Host test-codespace\n    IdentityFile {identity}\n",
        encoding="utf-8",
    )

    missing = run_command(
        [sys.executable, VALIDATE_SSH_CONFIG, config],
        cwd=tmp_path,
        check=False,
    )
    assert missing.returncode == 2
    assert "missing or unreadable key files" in missing.stdout
    assert "ssh-keygen" in missing.stdout

    identity.write_text("private", encoding="utf-8")
    Path(f"{identity}.pub").write_text("public", encoding="utf-8")
    ready = run_command([sys.executable, VALIDATE_SSH_CONFIG, config], cwd=tmp_path)
    assert ready.returncode == 0


def test_remote_make_command_preserves_an_encoded_target_as_one_argument(
    tmp_path: Path,
) -> None:
    target = "release candidate's [gpu]"
    encoded_target = base64.urlsafe_b64encode(target.encode("utf-8")).decode("ascii")
    result = run_command(
        [
            sys.executable,
            REMOTE_MAKE_COMMAND,
            "--source",
            "/workspace/source",
            "--makefile",
            "Makefile",
            "--jobs",
            "4",
            "--target-b64",
            encoded_target,
        ],
        cwd=tmp_path,
    )

    command = shlex.split(result.stdout)
    assert command[-2:] == ["--", target]
    assert not any(value.startswith("OUTPUT_DIR=") for value in command)
    assert not any(value.startswith("BUILD_DIR=") for value in command)
    assert not any(value.startswith("CLOUD_BACKEND=") for value in command)


def test_remote_collect_command_uses_a_safe_project_relative_directory(
    tmp_path: Path,
) -> None:
    encoded = base64.urlsafe_b64encode(b"dist/release files").decode("ascii")
    result = run_command(
        [
            sys.executable,
            REMOTE_COLLECT_COMMAND,
            "--source",
            "/workspace/source",
            "--directory-b64",
            encoded,
            "--archive",
            "/workspace/artifacts.tar.gz",
        ],
        cwd=tmp_path,
    )

    assert "/workspace/source/dist/release files" in result.stdout
    assert "tar -C" in result.stdout
    assert "/workspace/artifacts.tar.gz.tmp" in result.stdout


def test_remote_collect_command_rejects_path_traversal(tmp_path: Path) -> None:
    encoded = base64.urlsafe_b64encode(b"../escape").decode("ascii")
    result = run_command(
        [
            sys.executable,
            REMOTE_COLLECT_COMMAND,
            "--source",
            "/workspace/source",
            "--directory-b64",
            encoded,
            "--archive",
            "/workspace/artifacts.tar.gz",
        ],
        cwd=tmp_path,
        check=False,
    )

    assert result.returncode == 2
    assert "safe project-relative path" in result.stdout


@pytest.mark.parametrize(
    ("backend", "raw", "expected"),
    [
        ("colab-notebook", "running", "ready"),
        ("colab-notebook", "Status: IDLE", "ready"),
        ("kaggle-notebook", "complete", "succeeded"),
        ("codespaces-ssh", "Available", "ready"),
        ("colab-notebook", "not found", "absent"),
        ("kaggle-notebook", "ERROR", "failed"),
    ],
)
def test_status_normalization_has_one_cross_backend_vocabulary(
    tmp_path: Path, backend: str, raw: str, expected: str
) -> None:
    result = subprocess.run(
        [sys.executable, NORMALIZE_STATUS, "--backend", backend, "--json"],
        cwd=tmp_path,
        input=raw,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=True,
    )
    assert json.loads(result.stdout) == {"backend": backend, "status": expected}
