from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import stat
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = 1
EXCLUDED_ROOTS = {
    ".git",
    ".cloud-state",
    "artifacts",
}
SECRET_SCAN_BYTES = 2 * 1024 * 1024
SECRET_PATTERNS = (
    ("private key", re.compile(br"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----")),
    ("GitHub token", re.compile(br"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("GitHub token", re.compile(br"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
)
SUSPICIOUS_CREDENTIAL_NAMES = {
    ".env",
    ".env.local",
    "application_default_credentials.json",
    "credentials.json",
    "kaggle.json",
}


def ignore_patterns(root: Path) -> list[str]:
    path = root / ".cloudmakeignore"
    if not path.exists():
        return []
    patterns: list[str] = []
    for number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("!"):
            raise ValueError(
                f"{path}:{number}: negated patterns are not supported; list only exclusions"
            )
        patterns.append(line)
    return patterns


def custom_ignored(relative: str, is_directory: bool, patterns: Iterable[str]) -> bool:
    parts = relative.split("/")
    for original in patterns:
        pattern = original.replace("\\", "/")
        anchored = pattern.startswith("/")
        pattern = pattern.lstrip("/")
        directory_pattern = pattern.endswith("/")
        pattern = pattern.rstrip("/")
        if not pattern:
            continue

        if directory_pattern:
            if anchored or "/" in pattern:
                if relative == pattern or relative.startswith(pattern + "/"):
                    return True
            else:
                for index, part in enumerate(parts):
                    if fnmatch.fnmatchcase(part, pattern) and (
                        index < len(parts) - 1 or is_directory
                    ):
                        return True
            continue

        if anchored or "/" in pattern:
            if fnmatch.fnmatchcase(relative, pattern):
                return True
        elif any(fnmatch.fnmatchcase(part, pattern) for part in parts):
            return True
    return False


def included(path: Path, root: Path, patterns: Iterable[str]) -> bool:
    relative = path.relative_to(root)
    if relative.parts and relative.parts[0] in EXCLUDED_ROOTS:
        return False
    return not custom_ignored(relative.as_posix(), path.is_dir(), patterns)


def add_field(digest: Any, value: bytes) -> None:
    digest.update(len(value).to_bytes(8, "big"))
    digest.update(value)


def scan(root: Path) -> dict[str, Any]:
    patterns = ignore_patterns(root)
    paths: list[Path] = []
    for directory, directory_names, file_names in os.walk(
        root, topdown=True, followlinks=False
    ):
        directory_path = Path(directory)
        directory_names[:] = sorted(
            name
            for name in directory_names
            if directory_path != root or name not in EXCLUDED_ROOTS
        )
        for name in directory_names + sorted(file_names):
            path = directory_path / name
            if included(path, root, patterns):
                paths.append(path)

    digest = hashlib.sha256()
    entries: dict[str, dict[str, Any]] = {}
    total_bytes = 0
    for path in sorted(paths, key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        metadata = path.lstat()
        mode = oct(stat.S_IMODE(metadata.st_mode))
        entry: dict[str, Any] = {"mode": mode}

        if stat.S_ISLNK(metadata.st_mode):
            kind = "symlink"
            target = os.readlink(path)
            resolved_target = (path.parent / target).resolve()
            if resolved_target != root and root not in resolved_target.parents:
                raise ValueError(
                    f"source symlink escapes the project: {relative} -> {target}"
                )
            entry["target"] = target
        elif stat.S_ISDIR(metadata.st_mode):
            kind = "directory"
        elif stat.S_ISREG(metadata.st_mode):
            kind = "file"
            entry["size"] = metadata.st_size
            total_bytes += metadata.st_size
        else:
            raise ValueError(f"unsupported special source entry: {relative}")
        entry["kind"] = kind

        add_field(digest, relative.encode("utf-8", errors="surrogateescape"))
        add_field(digest, kind.encode("ascii"))
        add_field(digest, mode.encode("ascii"))

        if kind == "symlink":
            add_field(digest, entry["target"].encode("utf-8", errors="surrogateescape"))
        elif kind == "file":
            file_digest = hashlib.sha256()
            with path.open("rb") as source:
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    digest.update(chunk)
                    file_digest.update(chunk)
            entry["sha256"] = file_digest.hexdigest()
        entries[relative] = entry

    return {
        "schema": SCHEMA_VERSION,
        "fingerprint": digest.hexdigest(),
        "total_bytes": total_bytes,
        "entries": entries,
    }


def scan_secrets(root: Path, manifest: dict[str, Any]) -> tuple[list[str], list[str]]:
    blocked: list[str] = []
    warnings: list[str] = []
    for relative, entry in manifest["entries"].items():
        if entry["kind"] != "file":
            continue
        path = root / relative
        if path.name in SUSPICIOUS_CREDENTIAL_NAMES:
            warnings.append(f"credential-like filename: {relative}")
        with path.open("rb") as stream:
            content = stream.read(SECRET_SCAN_BYTES)
        if b"\0" in content[:8192]:
            continue
        for label, pattern in SECRET_PATTERNS:
            if pattern.search(content):
                blocked.append(f"{label}: {relative}")
                break
    return blocked, warnings


def atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def write_archive(root: Path, path: Path, manifest: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with tarfile.open(temporary, "w:gz") as archive:
            for relative in manifest["entries"]:
                archive.add(root / relative, arcname=relative, recursive=False)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema": SCHEMA_VERSION, "entries": {}}
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except Exception as error:
        raise ValueError(f"source manifest is corrupt: {path}") from error
    if manifest.get("schema") != SCHEMA_VERSION or not isinstance(
        manifest.get("entries"), dict
    ):
        raise ValueError(f"unsupported source manifest: {path}")
    return manifest


def print_plan(current: dict[str, Any], previous: dict[str, Any]) -> None:
    current_entries = current["entries"]
    previous_entries = previous["entries"]
    added = sorted(set(current_entries) - set(previous_entries))
    deleted = sorted(set(previous_entries) - set(current_entries))
    modified = sorted(
        path
        for path in set(current_entries) & set(previous_entries)
        if current_entries[path] != previous_entries[path]
    )
    for path in added:
        print(f"A {path}")
    for path in modified:
        print(f"M {path}")
    for path in deleted:
        print(f"D {path}")
    print(
        f"Source plan: {len(added)} added, {len(modified)} modified, "
        f"{len(deleted)} deleted; {current['total_bytes']} bytes selected."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Fingerprint and package cloudmake source")
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--compare", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--warn-mb", type=float, default=0)
    parser.add_argument("--max-mb", type=float, default=0)
    parser.add_argument("--allow-secrets", action="store_true")
    arguments = parser.parse_args()

    root = arguments.root.expanduser().resolve()
    manifest = scan(root)
    blocked_secrets, secret_warnings = scan_secrets(root, manifest)
    for warning in secret_warnings[:10]:
        print(f"[cloudmake] Warning: {warning}", file=sys.stderr)
    if len(secret_warnings) > 10:
        print(
            f"[cloudmake] Warning: {len(secret_warnings) - 10} additional credential-like filenames selected.",
            file=sys.stderr,
        )
    if blocked_secrets:
        severity = "Warning" if arguments.allow_secrets else "Refusing source transfer"
        for finding in blocked_secrets[:10]:
            print(f"[cloudmake] {severity}: detected {finding}", file=sys.stderr)
        if not arguments.allow_secrets:
            print(
                "[cloudmake] Exclude the file with .cloudmakeignore or deliberately set "
                "CLOUDMAKE_ALLOW_SECRETS=1.",
                file=sys.stderr,
            )
            return 2
    selected_mb = manifest["total_bytes"] / (1024 * 1024)
    if arguments.max_mb > 0 and selected_mb > arguments.max_mb:
        print(
            f"[cloudmake] source selection is {selected_mb:.1f} MiB, above "
            f"the configured {arguments.max_mb:.1f} MiB limit",
            file=sys.stderr,
        )
        return 2
    if arguments.warn_mb > 0 and selected_mb > arguments.warn_mb:
        print(
            f"[cloudmake] Warning: source selection is {selected_mb:.1f} MiB; "
            "consider adding exclusions to .cloudmakeignore.",
            file=sys.stderr,
        )

    if arguments.compare:
        print_plan(manifest, load_manifest(arguments.compare))
    if arguments.archive and not arguments.dry_run:
        write_archive(root, arguments.archive, manifest)
    if arguments.manifest and not arguments.dry_run:
        atomic_text(arguments.manifest, json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    if not arguments.dry_run:
        print(manifest["fingerprint"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
