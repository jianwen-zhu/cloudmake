#!/usr/bin/env python3
"""Write a terminal OCI receipt for provider-native environment execution."""

from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import re
import tempfile


IMAGE = re.compile(r"^[^\s@]+@(sha256:[0-9a-f]{64})$")


def decode(value: str, description: str) -> str:
    try:
        result = base64.urlsafe_b64decode(value.encode("ascii")).decode("utf-8")
    except Exception as error:
        raise SystemExit(f"invalid encoded {description}") from error
    if not result or "\n" in result or "\0" in result:
        raise SystemExit(f"invalid {description}")
    return result


def atomic_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--runtime", required=True)
    parser.add_argument("--image-b64", required=True)
    parser.add_argument("--target-b64", required=True)
    parser.add_argument("--exit-code", type=int, required=True)
    arguments = parser.parse_args()
    image = decode(arguments.image_b64, "OCI image")
    match = IMAGE.fullmatch(image)
    if match is None:
        parser.error("image must be an immutable OCI digest reference")
    target = decode(arguments.target_b64, "target")
    if not 0 <= arguments.exit_code <= 255:
        parser.error("exit code must be between 0 and 255")
    atomic_json(
        arguments.result,
        {
            "schema": 1,
            "mode": "run",
            "status": "succeeded" if arguments.exit_code == 0 else "target-failed",
            "runner": "oci",
            "runtime": arguments.runtime,
            "digest": match.group(1),
            "image_inspection": {
                "requested_digest": match.group(1),
                "provider_native": True,
            },
            "target": target,
            "exit_code": arguments.exit_code,
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
