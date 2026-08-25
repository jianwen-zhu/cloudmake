from __future__ import annotations

import io
import tarfile
from pathlib import Path

from conftest import PROJECT_ROOT, run_command


SCRIPT = PROJECT_ROOT / "tools" / "colab_sync.py"


def transformed_script(tmp_path: Path) -> Path:
    root = tmp_path / "remote" / "workspace"
    archive = tmp_path / "incoming" / "source.tar.gz"
    fingerprint = tmp_path / "incoming" / "source.sha256"
    owner = tmp_path / "incoming" / "owner.json"
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


def test_sync_atomically_replaces_source_and_fingerprint(tmp_path: Path) -> None:
    script = transformed_script(tmp_path)
    root = tmp_path / "remote" / "workspace"
    old_source = root / "src"
    old_source.mkdir(parents=True)
    (old_source / "stale.txt").write_text("stale", encoding="utf-8")
    incoming = tmp_path / "incoming"
    write_archive(
        incoming / "source.tar.gz",
        {"Makefile": b"all:\n\t@true\n", "src/main.c": b"int main(void) { return 0; }\n"},
    )
    (incoming / "source.sha256").write_text("abc123\n", encoding="utf-8")
    (incoming / "owner.json").write_text(
        '{"schema": 1, "project_id": "test", "project_name": "test", '
        '"source_path": "/test", "hostname": "test"}\n',
        encoding="utf-8",
    )

    result = run_command(["python3", script], cwd=tmp_path)

    assert "Synchronized source" in result.stdout
    assert not (old_source / "stale.txt").exists()
    assert (old_source / "src" / "main.c").is_file()
    assert (root / "source.sha256").read_text(encoding="utf-8") == "abc123\n"
    assert '"project_id": "test"' in (root / ".cloudmake-owner.json").read_text(
        encoding="utf-8"
    )
    assert not (root / "src.new").exists()
    assert not (root / "src.old").exists()


def test_sync_rejects_parent_path_traversal(tmp_path: Path) -> None:
    script = transformed_script(tmp_path)
    incoming = tmp_path / "incoming"
    write_archive(incoming / "source.tar.gz", {"../escaped.txt": b"not allowed"})
    (incoming / "source.sha256").write_text("unsafe\n", encoding="utf-8")
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
    incoming = tmp_path / "incoming"
    write_symlink_archive(incoming / "source.tar.gz", "escape", "../../outside")
    (incoming / "source.sha256").write_text("unsafe\n", encoding="utf-8")
    (incoming / "owner.json").write_text("{}", encoding="utf-8")

    result = run_command(["python3", script], cwd=tmp_path, check=False)

    assert result.returncode != 0
    assert "unsafe archive link" in result.stdout
    assert (source / "keep").read_text(encoding="utf-8") == "keep"
    assert not (tmp_path / "remote" / "outside").exists()
