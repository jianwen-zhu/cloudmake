from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


OWNER = Path("/content/.cloud-build/workspace/.cloudmake-owner.json")
FINGERPRINT = Path("/content/.cloud-build/workspace/source.sha256")
MARKER = re.compile(
    r"\[cloudmake\] control-state owner=(present|absent) "
    r"fingerprint=(present|absent)"
)


def remote_probe() -> int:
    owner = "present" if OWNER.is_file() else "absent"
    fingerprint = "present" if FINGERPRINT.is_file() else "absent"
    print(f"[cloudmake] control-state owner={owner} fingerprint={fingerprint}")
    return 0


def parse_receipt(path: Path, field: str) -> int:
    match = MARKER.search(path.read_text(encoding="utf-8", errors="replace"))
    if match is None:
        raise SystemExit("Colab control-state probe returned no valid marker")
    print(match.group(1 if field == "owner" else 2))
    return 0


def main() -> int:
    # `colab exec -f` evaluates this file inside an existing Jupyter kernel.
    # The kernel process contributes its own `-f <connection.json>` arguments;
    # an argument-free invocation is the remote probe and must not parse those
    # unrelated arguments. Host-side receipt parsing remains strict so a
    # misspelled Cloudmake option is never silently accepted.
    if "--parse" not in sys.argv[1:]:
        return remote_probe()
    parser = argparse.ArgumentParser(description="Probe or parse Colab control state")
    parser.add_argument("--parse", type=Path)
    parser.add_argument("--field", choices=("owner", "fingerprint"))
    arguments = parser.parse_args()
    if arguments.parse is None:
        if arguments.field is not None:
            parser.error("--field requires --parse")
        return remote_probe()
    if arguments.field is None:
        parser.error("--parse requires --field")
    return parse_receipt(arguments.parse, arguments.field)


if __name__ == "__main__":
    # IPython renders even successful SystemExit as a traceback. All failures
    # in this helper already raise directly, so returning normally keeps the
    # remote probe quiet without hiding errors.
    main()
