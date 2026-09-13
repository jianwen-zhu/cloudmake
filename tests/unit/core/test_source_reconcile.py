from __future__ import annotations

import json
from pathlib import Path

from conftest import PROJECT_ROOT, run_command


SCRIPT = PROJECT_ROOT / "tools" / "source_reconcile.py"


def write_manifest(path: Path, entries: dict[str, dict]) -> None:
    path.write_text(
        json.dumps({"schema": 1, "fingerprint": "test", "entries": entries}),
        encoding="utf-8",
    )


def build_script(tmp_path: Path, previous: dict[str, dict], current: dict[str, dict]) -> Path:
    previous_path = tmp_path / "previous.json"
    current_path = tmp_path / "current.json"
    script = tmp_path / "delete.sh"
    write_manifest(previous_path, previous)
    write_manifest(current_path, current)
    run_command(
        [
            "python3",
            SCRIPT,
            "--previous",
            previous_path,
            "--current",
            current_path,
            "--script",
            script,
        ],
        cwd=tmp_path,
    )
    return script


def test_deletion_removes_only_former_source_and_preserves_generated_files(
    tmp_path: Path,
) -> None:
    root = tmp_path / "remote"
    (root / "tree" / "generated").mkdir(parents=True)
    (root / "tree" / "source.txt").write_text("source", encoding="utf-8")
    (root / "tree" / "generated" / "result.bin").write_text(
        "generated", encoding="utf-8"
    )
    script = build_script(
        tmp_path,
        {
            "tree": {"kind": "directory"},
            "tree/source.txt": {"kind": "file"},
        },
        {},
    )

    run_command(["sh", script, root], cwd=tmp_path)

    assert not (root / "tree" / "source.txt").exists()
    assert (root / "tree" / "generated" / "result.bin").read_text() == "generated"


def test_deletion_handles_shell_metacharacters_as_literal_paths(tmp_path: Path) -> None:
    root = tmp_path / "remote"
    root.mkdir()
    unusual = "odd ' name $HOME\nline"
    (root / unusual).write_text("source", encoding="utf-8")
    script = build_script(tmp_path, {unusual: {"kind": "file"}}, {})

    run_command(["sh", script, root], cwd=tmp_path)

    assert not (root / unusual).exists()


def test_deletion_refuses_source_owned_type_change(tmp_path: Path) -> None:
    root = tmp_path / "remote"
    (root / "was-file").mkdir(parents=True)
    (root / "was-file" / "generated").write_text("keep", encoding="utf-8")
    script = build_script(tmp_path, {"was-file": {"kind": "file"}}, {})

    result = run_command(["sh", script, root], cwd=tmp_path, check=False)

    assert result.returncode == 2
    assert "changed type" in result.stdout
    assert (root / "was-file" / "generated").read_text() == "keep"


def test_manifest_path_traversal_is_rejected_before_script_creation(tmp_path: Path) -> None:
    previous = tmp_path / "previous.json"
    current = tmp_path / "current.json"
    script = tmp_path / "delete.sh"
    write_manifest(previous, {"../outside": {"kind": "file"}})
    write_manifest(current, {})

    result = run_command(
        [
            "python3",
            SCRIPT,
            "--previous",
            previous,
            "--current",
            current,
            "--script",
            script,
        ],
        cwd=tmp_path,
        check=False,
    )

    assert result.returncode != 0
    assert "unsafe source manifest path" in result.stdout
    assert not script.exists()


def test_invalid_manifest_kind_is_rejected_before_script_creation(tmp_path: Path) -> None:
    previous = tmp_path / "previous.json"
    current = tmp_path / "current.json"
    script = tmp_path / "delete.sh"
    write_manifest(previous, {"device": {"kind": "device"}})
    write_manifest(current, {})

    result = run_command(
        [
            "python3",
            SCRIPT,
            "--previous",
            previous,
            "--current",
            current,
            "--script",
            script,
        ],
        cwd=tmp_path,
        check=False,
    )

    assert result.returncode != 0
    assert "invalid source manifest entry" in result.stdout
    assert not script.exists()
