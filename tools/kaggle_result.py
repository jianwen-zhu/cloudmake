#!/usr/bin/env python3
"""Validate a Kaggle run receipt and atomically advance its checkpoint head."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any


def load(path: Path, description: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as error:
        raise RuntimeError(f"{description} is unavailable or invalid: {error}") from error
    if not isinstance(value, dict) or value.get("schema") != 1:
        raise RuntimeError(f"{description} has an unsupported schema")
    return value


def atomic_json(path: Path, value: dict[str, Any]) -> None:
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
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def field() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dispatch", type=Path, required=True)
    parser.add_argument("--field", choices=("kernel_ref", "previous_kernel_ref"), required=True)
    arguments = parser.parse_args()
    value = load(arguments.dispatch, "Kaggle dispatch receipt").get(arguments.field, "")
    if not isinstance(value, str) or "\n" in value:
        raise RuntimeError("Kaggle dispatch receipt contains an invalid reference")
    print(value)
    return 0


def complete() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dispatch", type=Path, required=True)
    parser.add_argument("--target-result", type=Path, required=True)
    parser.add_argument("--checkpoint-result", type=Path)
    parser.add_argument("--head", type=Path)
    parser.add_argument("--provenance", type=Path)
    parser.add_argument("--operation-state", type=Path)
    arguments = parser.parse_args()
    dispatch = load(arguments.dispatch, "Kaggle dispatch receipt")
    target = load(arguments.target_result, "Kaggle target receipt")
    status = target.get("status")
    if status not in {"succeeded", "target-failed", "infrastructure-failed"}:
        raise RuntimeError("Kaggle target receipt has an invalid status")
    submission = target.get("target_submission")
    retry_safe = target.get("retry_safe")
    phase = target.get("phase")
    if submission not in {"not_submitted", "submitted", "ambiguous"}:
        raise RuntimeError("Kaggle target receipt has an invalid submission state")
    if not isinstance(retry_safe, bool) or not isinstance(phase, str) or not phase:
        raise RuntimeError("Kaggle target receipt has invalid lifecycle evidence")
    if arguments.operation_state is not None:
        atomic_json(
            arguments.operation_state,
            {
                "schema": 1,
                "phase": phase,
                "provider_state": (
                    "succeeded" if status == "succeeded" else "failed"
                ),
                "target_submission": submission,
                "retry_safe": retry_safe,
            },
        )
    if status == "infrastructure-failed":
        raise RuntimeError(str(target.get("error", "Kaggle infrastructure failure")))
    exit_code = target.get("exit_code")
    if isinstance(exit_code, bool) or not isinstance(exit_code, int) or exit_code < 0:
        raise RuntimeError("Kaggle target receipt has an invalid exit status")
    if status == "target-failed":
        if dispatch.get("checkpoint"):
            print("[cloudmake] checkpoint=unchanged reason=target-failed", flush=True)
        return exit_code
    if dispatch.get("checkpoint"):
        if arguments.operation_state is not None:
            atomic_json(
                arguments.operation_state,
                {
                    "schema": 1,
                    "phase": "checkpoint_publication",
                    "provider_state": "unknown",
                    "target_submission": "submitted",
                    "retry_safe": False,
                },
            )
        if arguments.checkpoint_result is None or arguments.head is None:
            raise RuntimeError("checkpoint completion paths are required")
        checkpoint = load(arguments.checkpoint_result, "Kaggle checkpoint receipt")
        if (
            checkpoint.get("status") != "succeeded"
            or checkpoint.get("workspace_id") != dispatch.get("workspace_id")
            or checkpoint.get("snapshot") != dispatch.get("kernel_ref")
        ):
            raise RuntimeError("Kaggle checkpoint receipt does not match this dispatch")
        atomic_json(arguments.head, {
            "schema": 1,
            "workspace_id": dispatch["workspace_id"],
            "slot": dispatch["slot"],
            "kernel_ref": dispatch["kernel_ref"],
        })
        if arguments.provenance is not None:
            arguments.provenance.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(arguments.checkpoint_result, arguments.provenance)
        print(
            f"[cloudmake] checkpoint=published snapshot={dispatch['kernel_ref']}",
            flush=True,
        )
        if arguments.operation_state is not None:
            atomic_json(
                arguments.operation_state,
                {
                    "schema": 1,
                    "phase": "checkpoint_publication",
                    "provider_state": "succeeded",
                    "target_submission": "submitted",
                    "retry_safe": False,
                },
            )
    return exit_code


def slots() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--listing", type=Path, required=True)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--workspace-id", required=True)
    arguments = parser.parse_args()
    if re.fullmatch(r"[A-Za-z0-9._-]+", arguments.owner) is None or re.fullmatch(
        r"[0-9a-f]{24}", arguments.workspace_id
    ) is None:
        raise RuntimeError("invalid Kaggle workspace slot identity")
    try:
        listing = json.loads(arguments.listing.read_text(encoding="utf-8"))
    except Exception as error:
        raise RuntimeError(f"Kaggle kernel listing is unavailable or invalid: {error}") from error
    if not isinstance(listing, list):
        raise RuntimeError("Kaggle kernel listing has an invalid shape")
    expected = {
        f"{arguments.owner}/cloudmake-ws-{arguments.workspace_id}-{slot}"
        for slot in ("a", "b")
    }
    found: set[str] = set()
    for entry in listing:
        reference = entry.get("ref") if isinstance(entry, dict) else None
        if reference in expected:
            found.add(reference)
    for reference in sorted(found):
        print(reference)
    return 0


if __name__ == "__main__":
    try:
        command = os.sys.argv[1:2]
        os.sys.argv = [os.sys.argv[0], *os.sys.argv[2:]]
        if command == ["field"]:
            exit_code = field()
        elif command == ["complete"]:
            exit_code = complete()
        elif command == ["slots"]:
            exit_code = slots()
        else:
            raise RuntimeError("usage: kaggle_result.py {field|complete|slots} ...")
    except RuntimeError as error:
        print(f"[cloudmake] Kaggle infrastructure failure: {error}", file=os.sys.stderr)
        exit_code = 70
    raise SystemExit(exit_code)
