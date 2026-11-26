from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Print a file's SHA-256 digest")
    parser.add_argument("path", type=Path)
    arguments = parser.parse_args()
    print(sha256(arguments.path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
