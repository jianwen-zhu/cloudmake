from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create a source-bound Colab session preparation receipt"
    )
    parser.add_argument("--target", required=True)
    parser.add_argument("--source-fingerprint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    fingerprint = arguments.source_fingerprint.read_text(encoding="utf-8").strip()
    if len(fingerprint) != 64 or any(
        character not in "0123456789abcdef" for character in fingerprint
    ):
        parser.error("source fingerprint must contain one lowercase SHA-256 digest")
    value = {
        "schema": 1,
        "prepare_target": arguments.target,
        "source_fingerprint": fingerprint,
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{arguments.output.name}.", suffix=".tmp", dir=arguments.output.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, sort_keys=True, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, arguments.output)
    finally:
        temporary.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
