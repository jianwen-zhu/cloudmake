from __future__ import annotations

import inspect
import shutil
import tarfile
from pathlib import Path, PurePosixPath


ROOT = Path("/content/.cloud-build/workspace")
ARCHIVE = Path("/content/cloud-build-source.tar.gz")
INCOMING_FINGERPRINT = Path("/content/cloud-build-source.sha256")
INCOMING_OWNER = Path("/content/cloud-build-owner.json")
SOURCE = ROOT / "src"
STAGING = ROOT / "src.new"
OLD = ROOT / "src.old"
FINGERPRINT = ROOT / "source.sha256"
OWNER = ROOT / ".cloudmake-owner.json"


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
shutil.rmtree(STAGING, ignore_errors=True)
STAGING.mkdir(parents=True)

with tarfile.open(ARCHIVE, "r:gz") as archive:
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
