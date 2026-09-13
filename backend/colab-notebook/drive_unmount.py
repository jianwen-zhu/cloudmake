#!/usr/bin/env python3
"""Flush and unmount Drive after a Cloudmake checkpoint operation."""

import json
import os
from pathlib import Path
import tempfile

from google.colab import drive


RESULT = Path("/content/.cloud-build/checkpoint-unmount-result.json")


def write_result(status: str, error: str | None = None) -> None:
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{RESULT.name}.", suffix=".tmp", dir=RESULT.parent
    )
    temporary = Path(temporary_name)
    payload = {"schema": 1, "operation": "unmount", "status": status}
    if error:
        payload["error"] = error
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, sort_keys=True)
            stream.write("\n")
        os.chmod(temporary, 0o600)
        os.replace(temporary, RESULT)
    finally:
        temporary.unlink(missing_ok=True)


try:
    RESULT.unlink(missing_ok=True)
    if os.path.ismount("/content/drive"):
        drive.flush_and_unmount()
    if os.path.ismount("/content/drive"):
        raise RuntimeError("Google Drive remains mounted after unmount")
    write_result("succeeded")
    print("[cloudmake] checkpoint-drive=unmounted")
except BaseException as error:
    write_result("failed", str(error) or type(error).__name__)
    raise
