from __future__ import annotations

import inspect
import json
import os
import shutil
import stat
import tarfile
from pathlib import Path, PurePosixPath
from typing import Any


ROOT = Path("/content/.cloud-build/workspace")
ARCHIVE = Path("/content/cloud-build-source.tar.gz")
INCOMING_FINGERPRINT = Path("/content/cloud-build-source.sha256")
INCOMING_OWNER = Path("/content/cloud-build-owner.json")
INCOMING_MANIFEST = Path("/content/cloud-build-source-manifest.json")
INCOMING_PREVIOUS_MANIFEST = Path("/content/cloud-build-previous-manifest.json")
SOURCE = ROOT / "src"
STAGING = ROOT / "src.new"
OLD = ROOT / "src.old"
FINGERPRINT = ROOT / "source.sha256"
MANIFEST = ROOT / "source-manifest.json"
OWNER = ROOT / ".cloudmake-owner.json"
SYNC_RESULT = ROOT / "sync-result.sha256"
MANIFEST_SCHEMA = 1


def within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def extract_safely(archive: tarfile.TarFile) -> None:
    staging = STAGING.resolve()
    for member in archive.getmembers():
        member_path = PurePosixPath(member.name)
        if not member.name or member_path.is_absolute() or ".." in member_path.parts:
            raise ValueError(f"unsafe archive member: {member.name}")
        destination = (STAGING / Path(*member_path.parts)).resolve()
        if not within(destination, staging):
            raise ValueError(f"unsafe archive member: {member.name}")
        if member.ischr() or member.isblk() or member.isfifo() or member.isdev():
            raise ValueError(f"unsafe archive member type: {member.name}")
        if member.issym() or member.islnk():
            link_path = PurePosixPath(member.linkname)
            if link_path.is_absolute():
                raise ValueError(f"unsafe archive link: {member.name}")
            link_base = destination.parent if member.issym() else staging
            link_target = (link_base / Path(*link_path.parts)).resolve()
            if not within(link_target, staging):
                raise ValueError(f"unsafe archive link: {member.name}")

        options = (
            {"filter": "data"}
            if "filter" in inspect.signature(tarfile.TarFile.extract).parameters
            else {}
        )
        archive.extract(member, STAGING, **options)


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except Exception as error:
        raise ValueError(f"source manifest is corrupt: {path}") from error
    if manifest.get("schema") != MANIFEST_SCHEMA or not isinstance(
        manifest.get("entries"), dict
    ):
        raise ValueError(f"unsupported source manifest: {path}")
    return manifest


def installed_previous_manifest() -> dict[str, Any] | None:
    if MANIFEST.exists():
        return load_manifest(MANIFEST)
    if INCOMING_PREVIOUS_MANIFEST.exists() and FINGERPRINT.exists():
        candidate = load_manifest(INCOMING_PREVIOUS_MANIFEST)
        if candidate.get("fingerprint") == FINGERPRINT.read_text(
            encoding="utf-8"
        ).strip():
            return candidate
    return None


def workspace_entries(root: Path) -> list[Path]:
    entries: list[Path] = []
    for directory, directory_names, file_names in os.walk(
        root, topdown=True, followlinks=False
    ):
        directory_path = Path(directory)
        for name in sorted(directory_names):
            path = directory_path / name
            entries.append(path)
            if path.is_symlink():
                directory_names.remove(name)
        for name in sorted(file_names):
            entries.append(directory_path / name)
    return sorted(entries, key=lambda path: path.relative_to(root).as_posix())


def conflicts_with_source(relative: str, current: dict[str, Any]) -> bool:
    path = PurePosixPath(relative)
    entries = current["entries"]
    if relative in entries:
        return True
    for parent in path.parents:
        if parent == PurePosixPath("."):
            break
        entry = entries.get(parent.as_posix())
        if entry is not None and entry.get("kind") != "directory":
            return True
    return False


def preserve_generated(previous: dict[str, Any], current: dict[str, Any]) -> int:
    previous_entries = previous["entries"]
    preserved = 0
    for source in workspace_entries(SOURCE):
        relative = source.relative_to(SOURCE).as_posix()
        previous_entry = previous_entries.get(relative)
        metadata = source.lstat()
        actual_kind = (
            "symlink"
            if stat.S_ISLNK(metadata.st_mode)
            else "directory"
            if stat.S_ISDIR(metadata.st_mode)
            else "file"
            if stat.S_ISREG(metadata.st_mode)
            else "special"
        )
        if previous_entry is not None:
            if relative in current["entries"]:
                # The staged local source owns this exact path and replaces any
                # remote mutation, including a type change.
                continue
            if previous_entry.get("kind") != actual_kind:
                raise ValueError(
                    f"source-owned workspace path changed type: {relative}"
                )
            continue
        if actual_kind == "special":
            raise ValueError(f"unsupported generated workspace entry: {relative}")
        if conflicts_with_source(relative, current):
            continue

        destination = STAGING / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if actual_kind == "directory":
            destination.mkdir(exist_ok=True)
            destination.chmod(stat.S_IMODE(metadata.st_mode))
        elif actual_kind == "symlink":
            # Preserve the link object without resolving or following it.
            # Uploaded source links remain strictly confined by extract_safely;
            # this path handles only state created by already-running project code.
            destination.symlink_to(os.readlink(source))
        else:
            try:
                os.link(source, destination)
            except OSError:
                shutil.copy2(source, destination)
        preserved += 1
    return preserved


ROOT.mkdir(parents=True, exist_ok=True)
SYNC_RESULT.unlink(missing_ok=True)
current_manifest = load_manifest(INCOMING_MANIFEST)
incoming_fingerprint = INCOMING_FINGERPRINT.read_text(encoding="utf-8").strip()
if current_manifest.get("fingerprint") != incoming_fingerprint:
    raise ValueError("incoming source manifest does not match its fingerprint")
previous_manifest = installed_previous_manifest()
if SOURCE.exists() and previous_manifest is None:
    raise ValueError(
        "existing workspace has no matching source manifest; refusing to erase "
        "unclassified generated state"
    )
shutil.rmtree(STAGING, ignore_errors=True)
STAGING.mkdir(parents=True)

with tarfile.open(ARCHIVE, "r:gz") as archive:
    extract_safely(archive)

preserved = (
    preserve_generated(previous_manifest, current_manifest)
    if SOURCE.exists() and previous_manifest is not None
    else 0
)

shutil.rmtree(OLD, ignore_errors=True)
if SOURCE.exists():
    SOURCE.rename(OLD)
STAGING.rename(SOURCE)
shutil.rmtree(OLD, ignore_errors=True)

fingerprint_staging = FINGERPRINT.with_suffix(".sha256.new")
shutil.copyfile(INCOMING_FINGERPRINT, fingerprint_staging)
fingerprint_staging.replace(FINGERPRINT)

manifest_staging = MANIFEST.with_suffix(".json.new")
shutil.copyfile(INCOMING_MANIFEST, manifest_staging)
manifest_staging.replace(MANIFEST)

owner_staging = OWNER.with_suffix(".json.new")
shutil.copyfile(INCOMING_OWNER, owner_staging)
owner_staging.replace(OWNER)

result_staging = SYNC_RESULT.with_suffix(".sha256.new")
result_staging.write_text(f"{incoming_fingerprint}\n", encoding="utf-8")
result_staging.replace(SYNC_RESULT)

print(f"Synchronized source to {SOURCE}; preserved {preserved} generated entries")
