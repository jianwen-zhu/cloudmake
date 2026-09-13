from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate an OCI runner receipt")
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--expect", choices=("ready", "terminal"), required=True)
    parser.add_argument("--process-status", type=int)
    arguments = parser.parse_args()
    try:
        receipt = json.loads(arguments.result.read_text(encoding="utf-8"))
    except Exception as error:
        print(f"[cloudmake] OCI infrastructure failure: invalid runner receipt: {error}", file=sys.stderr)
        return 70
    if not isinstance(receipt, dict) or receipt.get("schema") != 1:
        print("[cloudmake] OCI infrastructure failure: invalid runner receipt schema", file=sys.stderr)
        return 70
    status = receipt.get("status")
    if arguments.expect == "ready":
        if arguments.process_status is not None:
            parser.error("--process-status is valid only with --expect terminal")
        if status == "ready":
            return 0
        print(
            f"[cloudmake] OCI infrastructure failure: {receipt.get('error', 'preflight did not become ready')}",
            file=sys.stderr,
        )
        return 70
    if status not in {"succeeded", "target-failed"}:
        print(
            f"[cloudmake] OCI infrastructure failure: {receipt.get('error', 'execution has no terminal target result')}",
            file=sys.stderr,
        )
        return 70
    exit_code = receipt.get("exit_code")
    if isinstance(exit_code, bool) or not isinstance(exit_code, int) or not 0 <= exit_code <= 255:
        print("[cloudmake] OCI infrastructure failure: invalid target exit status", file=sys.stderr)
        return 70
    if (
        arguments.process_status is not None
        and arguments.process_status != exit_code
    ):
        print(
            "[cloudmake] OCI infrastructure failure: remote process status "
            f"{arguments.process_status} does not match target receipt status {exit_code}",
            file=sys.stderr,
        )
        return 70
    if status == "target-failed":
        target = receipt.get("target")
        if not isinstance(target, str) or not target or "\n" in target:
            print("[cloudmake] OCI infrastructure failure: invalid target name", file=sys.stderr)
            return 70
        print(
            f"[cloudmake] target {target!r} failed with exit status {exit_code}",
            file=sys.stderr,
        )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
