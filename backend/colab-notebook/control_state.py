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
    owner = "present" if OWNER.exists() else "absent"
    fingerprint = "present" if FINGERPRINT.exists() else "absent"
    print(
        f"[cloudmake] control-state owner={owner} fingerprint={fingerprint}"
    )
    return 0


def parse_receipt(path: Path, field: str) -> int:
    match = MARKER.search(path.read_text(encoding="utf-8", errors="replace"))
    if match is None:
        raise SystemExit("Colab control-state probe returned no valid marker")
    print(match.group(1 if field == "owner" else 2))
    return 0


def main(argv: list[str] | None = None) -> int:
    arguments_list = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(description="Probe or parse Colab control state")
    parser.add_argument("--parse", type=Path)
    parser.add_argument("--field", choices=("owner", "fingerprint"))
    local_options = ("--parse", "--field")
    local_mode = any(
        argument == option or argument.startswith(option + "=")
        for argument in arguments_list
        for option in local_options
    )
    if not local_mode and not any(
        argument in {"-h", "--help"} for argument in arguments_list
    ):
        kernel_parser = argparse.ArgumentParser(add_help=False)
        kernel_parser.add_argument("-f", dest="kernel_connection_file")
        kernel_parser.parse_args(arguments_list)
        return remote_probe()

    arguments = parser.parse_args(arguments_list)
    if arguments.parse is None:
        if arguments.field is not None:
            parser.error("--field requires --parse")
        parser.error("remote probe mode accepts only notebook-kernel arguments")
    if arguments.field is None:
        parser.error("--parse requires --field")
    return parse_receipt(arguments.parse, arguments.field)


if __name__ == "__main__":
    exit_code = main()
    if exit_code:
        raise SystemExit(exit_code)
