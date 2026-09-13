from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any


def boolean(value: str) -> bool:
    if value == "true":
        return True
    if value == "false":
        return False
    raise argparse.ArgumentTypeError("expected true or false")


def load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"schema": 1}
    if not isinstance(value, dict):
        raise ValueError(f"operation state must be a JSON object: {path}")
    return value


def atomic_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def update(path: Path, values: dict[str, Any]) -> None:
    state = load(path)
    state.update({key: value for key, value in values.items() if value is not None})
    atomic_write(path, state)


def main() -> int:
    parser = argparse.ArgumentParser(description="Update Cloudmake operation state")
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--phase")
    parser.add_argument("--provider-state")
    parser.add_argument("--runtime-state")
    parser.add_argument("--session-created", type=boolean)
    parser.add_argument("--target-submission")
    parser.add_argument("--preparation-state")
    parser.add_argument("--retry-safe", type=boolean)
    parser.add_argument("--failure-code")
    arguments = parser.parse_args()
    update(
        arguments.file,
        {
            "phase": arguments.phase,
            "provider_state": arguments.provider_state,
            "runtime_state": arguments.runtime_state,
            "session_created": arguments.session_created,
            "target_submission": arguments.target_submission,
            "preparation_state": arguments.preparation_state,
            "retry_safe": arguments.retry_safe,
            "failure_code": arguments.failure_code,
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
