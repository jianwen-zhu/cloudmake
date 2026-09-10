#!/usr/bin/env python3
"""Classify a Codespace before the common SSH transport connects to it."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any


class CodespaceStateError(RuntimeError):
    """A provider-state response cannot safely drive the SSH connection."""


UNUSABLE_STATES = {"Archived", "Deleted", "Failed", "Unavailable"}


def atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(value)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def provider_state(gh: str, codespace: str) -> str:
    completed = subprocess.run(
        [gh, "codespace", "view", "-c", codespace, "--json", "state"],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode:
        detail = (completed.stderr or completed.stdout).strip()
        suffix = f": {detail}" if detail else ""
        raise CodespaceStateError(
            f"GitHub could not inspect Codespace {codespace!r}{suffix}"
        )
    try:
        payload: Any = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise CodespaceStateError(
            f"GitHub returned invalid state for Codespace {codespace!r}"
        ) from error
    state = payload.get("state") if isinstance(payload, dict) else None
    if not isinstance(state, str) or not state:
        raise CodespaceStateError(
            f"GitHub returned no state for Codespace {codespace!r}"
        )
    return state


def execution_state(state: str) -> str:
    if state in UNUSABLE_STATES:
        raise CodespaceStateError(
            f"Codespace is not connectable in provider state {state!r}"
        )
    # The following SSH connection wakes a stopped Codespace. Any other
    # connectable state represents an already active or provider-transitioning
    # resource that Cloudmake did not start.
    return "started" if state == "Shutdown" else "reused"


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--gh", default="gh")
    result.add_argument("--codespace", required=True)
    result.add_argument("--output", type=Path, required=True)
    return result


def main() -> int:
    arguments = parser().parse_args()
    arguments.output.unlink(missing_ok=True)
    try:
        state = provider_state(arguments.gh, arguments.codespace)
        atomic_text(arguments.output, execution_state(state))
    except (CodespaceStateError, OSError) as error:
        print(f"cloudmake: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
