from __future__ import annotations

import os
from pathlib import Path

from conftest import PROJECT_ROOT, run_command


SCRIPT = PROJECT_ROOT / "tools" / "source_fingerprint.py"


def fingerprint(directory: Path) -> str:
    result = run_command(["python3", SCRIPT], cwd=directory)
    value = result.stdout.strip()
    assert len(value) == 64
    int(value, 16)
    return value


def test_fingerprint_is_deterministic_and_independent_of_mtime(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    source = tmp_path / "src" / "main.c"
    source.write_text("int main(void) { return 0; }\n", encoding="utf-8")

    first = fingerprint(tmp_path)
    os.utime(source, (1_000_000, 1_000_000))
    second = fingerprint(tmp_path)

    assert first == second


def test_fingerprint_changes_for_content_mode_and_symlink_target(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("one\n", encoding="utf-8")
    link = tmp_path / "current"
    link.symlink_to("source.txt")

    initial = fingerprint(tmp_path)
    source.write_text("two\n", encoding="utf-8")
    content_changed = fingerprint(tmp_path)
    source.chmod(0o755)
    mode_changed = fingerprint(tmp_path)
    link.unlink()
    link.symlink_to("other.txt")
    link_changed = fingerprint(tmp_path)

    assert len({initial, content_changed, mode_changed, link_changed}) == 4


def test_fingerprint_ignores_only_cloudmake_owned_root_paths(tmp_path: Path) -> None:
    (tmp_path / "kept.txt").write_text("kept\n", encoding="utf-8")
    initial = fingerprint(tmp_path)

    for name in (".git", ".cloud-state", "artifacts"):
        directory = tmp_path / name
        directory.mkdir()
        (directory / "changing.txt").write_text(name, encoding="utf-8")
    assert fingerprint(tmp_path) == initial

    for name in ("build", ".venv", "__pycache__", ".pytest_cache"):
        directory = tmp_path / "any-layout" / name
        directory.mkdir(parents=True)
        (directory / "source.txt").write_text(name, encoding="utf-8")
    (tmp_path / "run_output.ipynb").write_text("generated", encoding="utf-8")

    assert fingerprint(tmp_path) != initial


def test_fingerprint_includes_empty_directories_and_names(tmp_path: Path) -> None:
    initial = fingerprint(tmp_path)
    (tmp_path / "empty").mkdir()
    with_directory = fingerprint(tmp_path)
    (tmp_path / "empty").rename(tmp_path / "renamed")
    renamed = fingerprint(tmp_path)

    assert len({initial, with_directory, renamed}) == 3
