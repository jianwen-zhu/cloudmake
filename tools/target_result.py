from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def read_result(path: Path) -> tuple[str, int]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as error:
        raise ValueError(f"cannot read target result {path}: {error}") from error
    if not isinstance(payload, dict) or payload.get("schema") != 1:
        raise ValueError(f"invalid target result schema in {path}")
    target = payload.get("target")
    exit_code = payload.get("exit_code")
    if not isinstance(target, str) or not target or "\n" in target:
        raise ValueError(f"invalid target name in {path}")
    if isinstance(exit_code, bool) or not isinstance(exit_code, int):
        raise ValueError(f"invalid target exit status in {path}")
    if not 0 <= exit_code <= 255:
        raise ValueError(f"target exit status is outside 0..255 in {path}")
    return target, exit_code


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Propagate an expected remote Make result without a notebook traceback"
    )
    parser.add_argument("--result", required=True, type=Path)
    arguments = parser.parse_args()
    try:
        target, exit_code = read_result(arguments.result)
    except ValueError as error:
        print(f"[cloudmake] infrastructure failure: {error}", file=sys.stderr)
        return 1
    if exit_code:
        print(
            f"[cloudmake] target {target!r} failed with exit status {exit_code}",
            file=sys.stderr,
        )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
