from __future__ import annotations

import argparse
import inspect
import math
import shutil
import tarfile
import uuid
from pathlib import Path, PurePosixPath


class UnsafeArchive(ValueError):
    pass


MIB = 1024 * 1024


def positive_number(value: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("must be a positive finite number")
    return number


def positive_integer(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def validate_member(member: tarfile.TarInfo) -> None:
    path = PurePosixPath(member.name)
    if not member.name or path.is_absolute() or ".." in path.parts:
        raise UnsafeArchive(f"unsafe archive path: {member.name!r}")
    if member.issym() or member.islnk():
        raise UnsafeArchive(f"artifact links are not accepted: {member.name!r}")
    if member.ischr() or member.isblk() or member.isfifo() or member.isdev():
        raise UnsafeArchive(f"special archive member is not accepted: {member.name!r}")


def validate_budget(
    archive_path: Path,
    members: list[tarfile.TarInfo],
    *,
    max_files: int,
    max_total_bytes: int,
    max_file_bytes: int,
    max_archive_bytes: int,
    max_ratio: float,
) -> None:
    archive_bytes = archive_path.stat().st_size
    if archive_bytes > max_archive_bytes:
        raise UnsafeArchive(
            f"artifact archive is {archive_bytes} bytes; limit is {max_archive_bytes}"
        )
    if len(members) > max_files:
        raise UnsafeArchive(
            f"artifact archive has {len(members)} members; limit is {max_files}"
        )
    file_members = [member for member in members if member.isfile()]
    oversized = next(
        (member for member in file_members if member.size > max_file_bytes), None
    )
    if oversized is not None:
        raise UnsafeArchive(
            f"artifact member {oversized.name!r} is {oversized.size} bytes; "
            f"per-file limit is {max_file_bytes}"
        )
    total_bytes = sum(member.size for member in file_members)
    if total_bytes > max_total_bytes:
        raise UnsafeArchive(
            f"artifact contents are {total_bytes} bytes; limit is {max_total_bytes}"
        )
    if archive_bytes and total_bytes / archive_bytes > max_ratio:
        raise UnsafeArchive(
            f"artifact expansion ratio is {total_bytes / archive_bytes:.1f}; "
            f"limit is {max_ratio:g}"
        )


def extract_atomically(
    archive_path: Path,
    destination: Path,
    *,
    max_files: int,
    max_total_bytes: int,
    max_file_bytes: int,
    max_archive_bytes: int,
    max_ratio: float,
) -> None:
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
            validate_budget(
                archive_path,
                members,
                max_files=max_files,
                max_total_bytes=max_total_bytes,
                max_file_bytes=max_file_bytes,
                max_archive_bytes=max_archive_bytes,
                max_ratio=max_ratio,
            )
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
    parser.add_argument("--max-files", type=positive_integer, default=50000)
    parser.add_argument("--max-total-mb", type=positive_number, default=2048)
    parser.add_argument("--max-file-mb", type=positive_number, default=1024)
    parser.add_argument("--max-archive-mb", type=positive_number, default=1024)
    parser.add_argument("--max-ratio", type=positive_number, default=500)
    arguments = parser.parse_args()
    extract_atomically(
        arguments.archive,
        arguments.destination,
        max_files=arguments.max_files,
        max_total_bytes=int(arguments.max_total_mb * MIB),
        max_file_bytes=int(arguments.max_file_mb * MIB),
        max_archive_bytes=int(arguments.max_archive_mb * MIB),
        max_ratio=arguments.max_ratio,
    )
    print(f"[cloudmake] Artifacts extracted to {arguments.destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
