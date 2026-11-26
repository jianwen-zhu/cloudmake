from __future__ import annotations

import hashlib
import inspect
import shutil
import tarfile
from pathlib import Path, PurePosixPath


ROOT = Path("/content/.cloud-build/workspace")
INCOMING = Path("/content")
ARCHIVE_DIGEST = Path("/content/cloud-build-source.archive.sha256")
INCOMING_FINGERPRINT = Path("/content/cloud-build-source.sha256")
INCOMING_OWNER = Path("/content/cloud-build-owner.json")
SOURCE = ROOT / "src"
STAGING = ROOT / "src.new"
OLD = ROOT / "src.old"
FINGERPRINT = ROOT / "source.sha256"
OWNER = ROOT / ".cloudmake-owner.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


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


ROOT.mkdir(parents=True, exist_ok=True)
expected_archive_digest = ARCHIVE_DIGEST.read_text(encoding="utf-8").strip()
if len(expected_archive_digest) != 64 or any(
    character not in "0123456789abcdef" for character in expected_archive_digest
):
    raise ValueError("invalid incoming source archive digest")
archive_path = INCOMING / f"cloud-build-source-{expected_archive_digest}.tar.gz"
if sha256(archive_path) != expected_archive_digest:
    raise ValueError("incoming source archive digest mismatch")
shutil.rmtree(STAGING, ignore_errors=True)
STAGING.mkdir(parents=True)

with tarfile.open(archive_path, "r:gz") as archive:
    extract_safely(archive)

shutil.rmtree(OLD, ignore_errors=True)
if SOURCE.exists():
    SOURCE.rename(OLD)
STAGING.rename(SOURCE)
shutil.rmtree(OLD, ignore_errors=True)

fingerprint_staging = FINGERPRINT.with_suffix(".sha256.new")
shutil.copyfile(INCOMING_FINGERPRINT, fingerprint_staging)
fingerprint_staging.replace(FINGERPRINT)

owner_staging = OWNER.with_suffix(".json.new")
shutil.copyfile(INCOMING_OWNER, owner_staging)
owner_staging.replace(OWNER)

print(f"Synchronized source to {SOURCE}")
