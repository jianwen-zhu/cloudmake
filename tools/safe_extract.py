from __future__ import annotations

import argparse
import inspect
import shutil
import tarfile
import uuid
from pathlib import Path, PurePosixPath


class UnsafeArchive(ValueError):
    pass


def validate_member(member: tarfile.TarInfo) -> None:
    path = PurePosixPath(member.name)
    if not member.name or path.is_absolute() or ".." in path.parts:
        raise UnsafeArchive(f"unsafe archive path: {member.name!r}")
    if member.issym() or member.islnk():
        raise UnsafeArchive(f"artifact links are not accepted: {member.name!r}")
    if member.ischr() or member.isblk() or member.isfifo() or member.isdev():
        raise UnsafeArchive(f"special archive member is not accepted: {member.name!r}")


def extract_atomically(archive_path: Path, destination: Path) -> None:
    archive_path = archive_path.resolve()
    if destination.is_symlink():
        raise UnsafeArchive(f"artifact destination must not be a symlink: {destination}")
    if destination.exists() and not destination.is_dir():
        raise UnsafeArchive(f"artifact destination is not a directory: {destination}")
    destination = destination.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.parent / f".{destination.name}.new-{uuid.uuid4().hex}"
    previous = destination.parent / f".{destination.name}.old-{uuid.uuid4().hex}"
    staging.mkdir()
    moved_previous = False
    try:
        with tarfile.open(archive_path, "r:*") as archive:
            members = archive.getmembers()
            for member in members:
                validate_member(member)
            options = (
                {"filter": "data"}
                if "filter" in inspect.signature(tarfile.TarFile.extractall).parameters
                else {}
            )
            archive.extractall(staging, members=members, **options)

        if destination.exists():
            destination.rename(previous)
            moved_previous = True
        staging.rename(destination)
        if moved_previous:
            shutil.rmtree(previous)
    except Exception:
        if moved_previous and not destination.exists() and previous.exists():
            previous.rename(destination)
        raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(previous, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Safely extract a cloudmake artifact archive")
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    arguments = parser.parse_args()
    extract_atomically(arguments.archive, arguments.destination)
    print(f"[cloudmake] Artifacts extracted to {arguments.destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
