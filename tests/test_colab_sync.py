from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path

from conftest import PROJECT_ROOT, run_command


SCRIPT = PROJECT_ROOT / "tools" / "colab_sync.py"


def transformed_script(tmp_path: Path) -> Path:
    root = tmp_path / "remote" / "workspace"
    archive = tmp_path / "incoming" / "source.tar.gz"
    fingerprint = tmp_path / "incoming" / "source.sha256"
    owner = tmp_path / "incoming" / "owner.json"
    manifest = tmp_path / "incoming" / "source-manifest.json"
    previous_manifest = tmp_path / "incoming" / "previous-manifest.json"
    source = SCRIPT.read_text(encoding="utf-8")
    source = source.replace(
        'ROOT = Path("/content/.cloud-build/workspace")', f"ROOT = Path({str(root)!r})"
    )
    source = source.replace(
        'ARCHIVE = Path("/content/cloud-build-source.tar.gz")',
        f"ARCHIVE = Path({str(archive)!r})",
    )
    source = source.replace(
        'INCOMING_FINGERPRINT = Path("/content/cloud-build-source.sha256")',
        f"INCOMING_FINGERPRINT = Path({str(fingerprint)!r})",
    )
    source = source.replace(
        'INCOMING_OWNER = Path("/content/cloud-build-owner.json")',
        f"INCOMING_OWNER = Path({str(owner)!r})",
    )
    source = source.replace(
        'INCOMING_MANIFEST = Path("/content/cloud-build-source-manifest.json")',
        f"INCOMING_MANIFEST = Path({str(manifest)!r})",
    )
    source = source.replace(
        'INCOMING_PREVIOUS_MANIFEST = Path("/content/cloud-build-previous-manifest.json")',
        f"INCOMING_PREVIOUS_MANIFEST = Path({str(previous_manifest)!r})",
    )
    generated = tmp_path / "colab_sync_under_test.py"
    generated.write_text(source, encoding="utf-8")
    return generated


def write_archive(path: Path, members: dict[str, bytes]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(path, "w:gz") as archive:
        for name, payload in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            info.mode = 0o644
            archive.addfile(info, io.BytesIO(payload))


def write_symlink_archive(path: Path, name: str, target: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(path, "w:gz") as archive:
        info = tarfile.TarInfo(name)
        info.type = tarfile.SYMTYPE
        info.linkname = target
        archive.addfile(info)


def write_manifest(path: Path, fingerprint: str, entries: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema": 1,
                "fingerprint": fingerprint,
                "total_bytes": sum(entry.get("size", 0) for entry in entries.values()),
                "entries": entries,
            }
        ),
        encoding="utf-8",
    )


def test_sync_atomically_replaces_source_and_fingerprint(tmp_path: Path) -> None:
    script = transformed_script(tmp_path)
    root = tmp_path / "remote" / "workspace"
    old_source = root / "src"
    incoming = tmp_path / "incoming"
    write_archive(
        incoming / "source.tar.gz",
        {"Makefile": b"all:\n\t@true\n", "src/main.c": b"int main(void) { return 0; }\n"},
    )
    (incoming / "source.sha256").write_text("abc123\n", encoding="utf-8")
    write_manifest(
        incoming / "source-manifest.json",
        "abc123",
        {
            "Makefile": {"kind": "file", "mode": "0o644", "size": 11},
            "src": {"kind": "directory", "mode": "0o755"},
            "src/main.c": {"kind": "file", "mode": "0o644", "size": 29},
        },
    )
    (incoming / "owner.json").write_text(
        '{"schema": 1, "project_id": "test", "project_name": "test", '
        '"source_path": "/test", "hostname": "test"}\n',
        encoding="utf-8",
    )

    result = run_command(["python3", script], cwd=tmp_path)

    assert "Synchronized source" in result.stdout
    assert (old_source / "src" / "main.c").is_file()
    assert (root / "source.sha256").read_text(encoding="utf-8") == "abc123\n"
    assert (root / "sync-result.sha256").read_text(encoding="utf-8") == "abc123\n"
    assert '"project_id": "test"' in (root / ".cloudmake-owner.json").read_text(
        encoding="utf-8"
    )
    assert not (root / "src.new").exists()
    assert not (root / "src.old").exists()


def test_sync_preserves_generated_outputs_but_removes_deleted_source(tmp_path: Path) -> None:
    script = transformed_script(tmp_path)
    root = tmp_path / "remote" / "workspace"
    source = root / "src"
    (source / "src").mkdir(parents=True)
    (source / "src" / "deleted.c").write_text("old source", encoding="utf-8")
    (source / "build").mkdir()
    (source / "build" / "result.bin").write_bytes(b"generated")
    previous_entries = {
        "src": {"kind": "directory", "mode": "0o755"},
        "src/deleted.c": {
            "kind": "file",
            "mode": "0o644",
            "size": 10,
            "sha256": "unused",
        },
    }
    (root / "source.sha256").write_text("previous\n", encoding="utf-8")
    write_manifest(root / "source-manifest.json", "previous", previous_entries)

    incoming = tmp_path / "incoming"
    write_archive(incoming / "source.tar.gz", {"Makefile": b"all:\n\t@true\n"})
    (incoming / "source.sha256").write_text("current\n", encoding="utf-8")
    write_manifest(
        incoming / "source-manifest.json",
        "current",
        {"Makefile": {"kind": "file", "mode": "0o644", "size": 11}},
    )
    (incoming / "owner.json").write_text("{}", encoding="utf-8")

    result = run_command(["python3", script], cwd=tmp_path)

    assert "preserved 2 generated entries" in result.stdout
    assert (source / "build" / "result.bin").read_bytes() == b"generated"
    assert not (source / "src" / "deleted.c").exists()


def test_sync_preserves_generated_absolute_symlink_without_following_it(
    tmp_path: Path,
) -> None:
    script = transformed_script(tmp_path)
    root = tmp_path / "remote" / "workspace"
    source = root / "src"
    source.mkdir(parents=True)
    generated = source / "tool-link"
    generated.symlink_to("/nix/store/example-tool/bin/tool")
    (root / "source.sha256").write_text("previous\n", encoding="utf-8")
    write_manifest(root / "source-manifest.json", "previous", {})
    incoming = tmp_path / "incoming"
    write_archive(incoming / "source.tar.gz", {"Makefile": b"all:\n\t@true\n"})
    (incoming / "source.sha256").write_text("current\n", encoding="utf-8")
    write_manifest(
        incoming / "source-manifest.json",
        "current",
        {"Makefile": {"kind": "file", "mode": "0o644", "size": 11}},
    )
    (incoming / "owner.json").write_text("{}", encoding="utf-8")

    run_command(["python3", script], cwd=tmp_path)

    assert generated.is_symlink()
    assert generated.readlink().as_posix() == "/nix/store/example-tool/bin/tool"


def test_sync_local_source_wins_generated_path_conflict(tmp_path: Path) -> None:
    script = transformed_script(tmp_path)
    root = tmp_path / "remote" / "workspace"
    source = root / "src"
    source.mkdir(parents=True)
    (source / "result.txt").write_text("generated", encoding="utf-8")
    (root / "source.sha256").write_text("previous\n", encoding="utf-8")
    write_manifest(root / "source-manifest.json", "previous", {})
    incoming = tmp_path / "incoming"
    write_archive(incoming / "source.tar.gz", {"result.txt": b"local"})
    (incoming / "source.sha256").write_text("current\n", encoding="utf-8")
    write_manifest(
        incoming / "source-manifest.json",
        "current",
        {"result.txt": {"kind": "file", "mode": "0o644", "size": 5}},
    )
    (incoming / "owner.json").write_text("{}", encoding="utf-8")

    run_command(["python3", script], cwd=tmp_path)

    assert (source / "result.txt").read_text(encoding="utf-8") == "local"


def test_sync_local_source_wins_remote_type_mutation(tmp_path: Path) -> None:
    script = transformed_script(tmp_path)
    root = tmp_path / "remote" / "workspace"
    source = root / "src"
    (source / "owned.txt").mkdir(parents=True)
    (source / "owned.txt" / "remote-child").write_text("remote", encoding="utf-8")
    (root / "source.sha256").write_text("previous\n", encoding="utf-8")
    write_manifest(
        root / "source-manifest.json",
        "previous",
        {"owned.txt": {"kind": "file", "mode": "0o644", "size": 3}},
    )
    incoming = tmp_path / "incoming"
    write_archive(incoming / "source.tar.gz", {"owned.txt": b"local"})
    (incoming / "source.sha256").write_text("current\n", encoding="utf-8")
    write_manifest(
        incoming / "source-manifest.json",
        "current",
        {"owned.txt": {"kind": "file", "mode": "0o644", "size": 5}},
    )
    (incoming / "owner.json").write_text("{}", encoding="utf-8")

    run_command(["python3", script], cwd=tmp_path)

    assert (source / "owned.txt").read_text(encoding="utf-8") == "local"


def test_sync_migrates_using_matching_host_previous_manifest(tmp_path: Path) -> None:
    script = transformed_script(tmp_path)
    root = tmp_path / "remote" / "workspace"
    source = root / "src"
    source.mkdir(parents=True)
    (source / "old-source.txt").write_text("old", encoding="utf-8")
    (source / "generated.bin").write_text("generated", encoding="utf-8")
    (root / "source.sha256").write_text("previous\n", encoding="utf-8")
    incoming = tmp_path / "incoming"
    write_manifest(
        incoming / "previous-manifest.json",
        "previous",
        {"old-source.txt": {"kind": "file", "mode": "0o644", "size": 3}},
    )
    write_archive(incoming / "source.tar.gz", {"current.txt": b"current"})
    (incoming / "source.sha256").write_text("current\n", encoding="utf-8")
    write_manifest(
        incoming / "source-manifest.json",
        "current",
        {"current.txt": {"kind": "file", "mode": "0o644", "size": 7}},
    )
    (incoming / "owner.json").write_text("{}", encoding="utf-8")

    run_command(["python3", script], cwd=tmp_path)

    assert not (source / "old-source.txt").exists()
    assert (source / "generated.bin").read_text(encoding="utf-8") == "generated"
    assert (source / "current.txt").read_text(encoding="utf-8") == "current"


def test_sync_refuses_unclassified_existing_workspace(tmp_path: Path) -> None:
    script = transformed_script(tmp_path)
    root = tmp_path / "remote" / "workspace"
    source = root / "src"
    source.mkdir(parents=True)
    (source / "unknown.bin").write_text("unknown", encoding="utf-8")
    incoming = tmp_path / "incoming"
    write_archive(incoming / "source.tar.gz", {"current.txt": b"current"})
    (incoming / "source.sha256").write_text("current\n", encoding="utf-8")
    write_manifest(
        incoming / "source-manifest.json",
        "current",
        {"current.txt": {"kind": "file", "mode": "0o644", "size": 7}},
    )
    (incoming / "owner.json").write_text("{}", encoding="utf-8")

    result = run_command(["python3", script], cwd=tmp_path, check=False)

    assert result.returncode != 0
    assert "refusing to erase unclassified generated state" in result.stdout
    assert not (root / "sync-result.sha256").exists()
    assert (source / "unknown.bin").read_text(encoding="utf-8") == "unknown"


def test_sync_rejects_parent_path_traversal(tmp_path: Path) -> None:
    script = transformed_script(tmp_path)
    incoming = tmp_path / "incoming"
    write_archive(incoming / "source.tar.gz", {"../escaped.txt": b"not allowed"})
    (incoming / "source.sha256").write_text("unsafe\n", encoding="utf-8")
    write_manifest(incoming / "source-manifest.json", "unsafe", {})
    (incoming / "owner.json").write_text("{}", encoding="utf-8")

    result = run_command(["python3", script], cwd=tmp_path, check=False)

    assert result.returncode != 0
    assert "unsafe archive member" in result.stdout
    assert not (tmp_path / "remote" / "escaped.txt").exists()
    assert not (tmp_path / "escaped.txt").exists()


def test_sync_rejects_absolute_archive_member(tmp_path: Path) -> None:
    script = transformed_script(tmp_path)
    incoming = tmp_path / "incoming"
    absolute_target = tmp_path / "absolute-escape.txt"
    write_archive(incoming / "source.tar.gz", {str(absolute_target): b"not allowed"})
    (incoming / "source.sha256").write_text("unsafe\n", encoding="utf-8")
    write_manifest(incoming / "source-manifest.json", "unsafe", {})
    (incoming / "owner.json").write_text("{}", encoding="utf-8")

    result = run_command(["python3", script], cwd=tmp_path, check=False)

    assert result.returncode != 0
    assert "unsafe archive member" in result.stdout
    assert not absolute_target.exists()


def test_sync_rejects_symlink_escape_before_replacing_source(tmp_path: Path) -> None:
    script = transformed_script(tmp_path)
    root = tmp_path / "remote" / "workspace"
    source = root / "src"
    source.mkdir(parents=True)
    (source / "keep").write_text("keep", encoding="utf-8")
    (root / "source.sha256").write_text("previous\n", encoding="utf-8")
    write_manifest(
        root / "source-manifest.json",
        "previous",
        {"keep": {"kind": "file", "mode": "0o644", "size": 4}},
    )
    incoming = tmp_path / "incoming"
    write_symlink_archive(incoming / "source.tar.gz", "escape", "../../outside")
    (incoming / "source.sha256").write_text("unsafe\n", encoding="utf-8")
    write_manifest(incoming / "source-manifest.json", "unsafe", {})
    (incoming / "owner.json").write_text("{}", encoding="utf-8")

    result = run_command(["python3", script], cwd=tmp_path, check=False)

    assert result.returncode != 0
    assert "unsafe archive link" in result.stdout
    assert (source / "keep").read_text(encoding="utf-8") == "keep"
    assert not (tmp_path / "remote" / "outside").exists()
