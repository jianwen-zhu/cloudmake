from __future__ import annotations

import argparse
import shlex
from pathlib import Path, PurePosixPath
from typing import Any

from source_fingerprint import load_manifest


def validate_relative(value: str) -> None:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts:
        raise ValueError(f"unsafe source manifest path: {value}")


def shell_path(relative: str) -> str:
    validate_relative(relative)
    return '"$root"/' + shlex.quote(relative)


def validate_manifest(manifest: dict[str, Any]) -> None:
    for relative, entry in manifest["entries"].items():
        validate_relative(relative)
        if not isinstance(entry, dict) or entry.get("kind") not in {
            "file",
            "directory",
            "symlink",
        }:
            raise ValueError(f"invalid source manifest entry: {relative}")


def deletion_script(previous: dict[str, Any], current: dict[str, Any]) -> str:
    previous_entries = previous["entries"]
    deleted = set(previous_entries) - set(current["entries"])
    non_directories = sorted(
        (path for path in deleted if previous_entries[path].get("kind") != "directory"),
        key=lambda value: (value.count("/"), value),
        reverse=True,
    )
    directories = sorted(
        (path for path in deleted if previous_entries[path].get("kind") == "directory"),
        key=lambda value: (value.count("/"), value),
        reverse=True,
    )

    lines = ["#!/bin/sh", "set -eu", 'root=$1']
    for relative in non_directories:
        target = shell_path(relative)
        label = shlex.quote(relative)
        lines.extend(
            [
                f'if [ -L {target} ] || [ -f {target} ]; then',
                f"  rm -f -- {target}",
                f'elif [ -e {target} ]; then',
                f"  printf '%s%s\\n' 'source-owned path changed type: ' {label} >&2",
                "  exit 2",
                "fi",
            ]
        )
    for relative in directories:
        target = shell_path(relative)
        label = shlex.quote(relative)
        lines.extend(
            [
                f'if [ -L {target} ] || {{ [ -e {target} ] && [ ! -d {target} ]; }}; then',
                f"  printf '%s%s\\n' 'source-owned path changed type: ' {label} >&2",
                "  exit 2",
                f'elif [ -d {target} ]; then',
                f"  rmdir -- {target} 2>/dev/null || :",
                "fi",
            ]
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create a safe remote deletion plan for source reconciliation"
    )
    parser.add_argument("--previous", type=Path, required=True)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--script", type=Path, required=True)
    arguments = parser.parse_args()

    previous = load_manifest(arguments.previous)
    current = load_manifest(arguments.current)
    validate_manifest(previous)
    validate_manifest(current)
    script = deletion_script(previous, current)
    arguments.script.parent.mkdir(parents=True, exist_ok=True)
    temporary = arguments.script.with_name(f".{arguments.script.name}.tmp")
    try:
        temporary.write_text(script, encoding="utf-8")
        temporary.replace(arguments.script)
    finally:
        temporary.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
