from __future__ import annotations

import argparse
import base64
import json
import shlex
import sys
from pathlib import PurePosixPath


def decode_arguments(value: str) -> list[str]:
    try:
        payload = base64.urlsafe_b64decode(value.encode("ascii"))
        arguments = json.loads(payload.decode("utf-8"))
    except Exception as error:
        raise ValueError("project arguments are not valid encoded JSON") from error
    if not isinstance(arguments, list) or not all(
        isinstance(argument, str) for argument in arguments
    ):
        raise ValueError("project arguments must be a JSON string list")
    return arguments


def main() -> int:
    parser = argparse.ArgumentParser(description="Construct a quoted remote Make command")
    parser.add_argument("--source", required=True)
    parser.add_argument("--makefile", required=True)
    parser.add_argument("--jobs", type=int, required=True)
    parser.add_argument("--target", default="")
    parser.add_argument("--target-b64", default="")
    parser.add_argument("--arguments-b64", default="W10=")
    arguments = parser.parse_args()

    if arguments.jobs < 1:
        parser.error("--jobs must be positive")
    if bool(arguments.target) == bool(arguments.target_b64):
        parser.error("exactly one of --target and --target-b64 is required")
    if arguments.target_b64:
        try:
            target = base64.b64decode(
                arguments.target_b64.encode("ascii"), altchars=b"-_", validate=True
            ).decode("utf-8")
        except Exception as error:
            parser.error(f"invalid --target-b64: {error}")
    else:
        target = arguments.target
    if not target or "\n" in target:
        parser.error("--target must be a non-empty single-line name")
    makefile = PurePosixPath(arguments.makefile)
    if not arguments.makefile or makefile.is_absolute() or ".." in makefile.parts:
        parser.error("--makefile must be a safe relative path")

    try:
        project_arguments = decode_arguments(arguments.arguments_b64)
    except ValueError as error:
        print(f"cloudmake: {error}", file=sys.stderr)
        return 2

    command = [
        "make",
        "-C",
        arguments.source,
        "-f",
        arguments.makefile,
        *project_arguments,
        f"-j{arguments.jobs}",
        "--",
        target,
    ]
    print(shlex.join(command))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
