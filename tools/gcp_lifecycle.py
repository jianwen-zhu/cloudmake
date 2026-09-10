#!/usr/bin/env python3
"""Bounded lifecycle and capability checks for an existing Compute Engine VM."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from typing import Any


RUNNING = "RUNNING"
STOPPED = {"TERMINATED", "SUSPENDED"}
STARTING = {"PROVISIONING", "STAGING"}
STOPPING = {"STOPPING", "SUSPENDING"}
SUPPORTED_STATES = {RUNNING, *STOPPED, *STARTING, *STOPPING, "REPAIRING"}
FREE_TIER_REGIONS = {"us-west1", "us-central1", "us-east1"}


class LifecycleError(RuntimeError):
    pass


def provider(
    gcloud: str, arguments: list[str], *, operation: str, check: bool = True
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [gcloud, *arguments],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise LifecycleError(
            f"Google Compute Engine {operation} failed"
            + (f": {detail}" if detail else "")
        )
    return result


def describe(gcloud: str, project: str, zone: str, instance: str) -> dict[str, Any]:
    result = provider(
        gcloud,
        [
            "compute",
            "instances",
            "describe",
            instance,
            "--project",
            project,
            "--zone",
            zone,
            "--format=json",
        ],
        operation="instance description",
    )
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise LifecycleError(
            "Google Compute Engine returned malformed instance data"
        ) from error
    if not isinstance(value, dict):
        raise LifecycleError("Google Compute Engine returned invalid instance data")
    status = value.get("status")
    if status not in SUPPORTED_STATES:
        raise LifecycleError(
            f"Compute Engine reported unsupported instance state {status!r}"
        )
    return value


def tail(value: object) -> str:
    return str(value or "unknown").rstrip("/").rsplit("/", 1)[-1]


def instance_profile(value: dict[str, Any], zone: str) -> dict[str, Any]:
    accelerators = value.get("guestAccelerators", [])
    if not isinstance(accelerators, list):
        accelerators = []
    accelerator_names = [
        f"{tail(item.get('acceleratorType'))}x{item.get('acceleratorCount', 1)}"
        for item in accelerators
        if isinstance(item, dict)
    ]
    machine = tail(value.get("machineType"))
    region = zone.rsplit("-", 1)[0] if "-" in zone else zone
    eligible_baseline = (
        machine == "e2-micro" and region in FREE_TIER_REGIONS and not accelerator_names
    )
    return {
        "machine_type": machine,
        "accelerators": accelerator_names,
        "status": value["status"],
        "region": region,
        "free_tier_compute_shape": eligible_baseline,
        "billing_exposure": "conditional-free-allowance"
        if eligible_baseline
        else "paid-capable",
    }


def publish(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def wait_for(
    gcloud: str,
    project: str,
    zone: str,
    instance: str,
    expected: set[str],
    *,
    timeout: float,
    poll_interval: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while True:
        value = describe(gcloud, project, zone, instance)
        if value["status"] in expected:
            return value
        if time.monotonic() >= deadline:
            raise LifecycleError(
                f"Compute Engine instance did not reach {', '.join(sorted(expected))} "
                f"within {timeout:g}s (last state: {value['status']})"
            )
        time.sleep(min(poll_interval, max(0.0, deadline - time.monotonic())))


def compact_context(profile: dict[str, Any]) -> str:
    fields = [
        f"machine={profile['machine_type']}",
        f"lifecycle={profile['status'].lower()}",
        f"billing={profile['billing_exposure']}",
    ]
    if profile["accelerators"]:
        fields.insert(1, f"accelerator={','.join(profile['accelerators'])}")
    return "[gcp] " + " ".join(fields)


def ensure_running(arguments: argparse.Namespace) -> int:
    value = describe(
        arguments.gcloud, arguments.project, arguments.zone, arguments.instance
    )
    profile = instance_profile(value, arguments.zone)
    print(compact_context(profile), flush=True)
    if not profile["free_tier_compute_shape"]:
        print(
            "[cloudmake] warning: selected GCP resource is paid-capable; "
            "provider billing and quota remain authoritative.",
            file=sys.stderr,
            flush=True,
        )
    initial = value["status"]
    if initial == RUNNING:
        outcome = "reused"
    elif initial in STARTING:
        value = wait_for(
            arguments.gcloud,
            arguments.project,
            arguments.zone,
            arguments.instance,
            {RUNNING},
            timeout=arguments.timeout,
            poll_interval=arguments.poll_interval,
        )
        outcome = "reused"
    elif initial in STOPPED:
        operation = "resume" if initial == "SUSPENDED" else "start"
        provider(
            arguments.gcloud,
            [
                "compute",
                "instances",
                operation,
                arguments.instance,
                "--project",
                arguments.project,
                "--zone",
                arguments.zone,
                "--quiet",
            ],
            operation=f"instance {operation}",
        )
        value = wait_for(
            arguments.gcloud,
            arguments.project,
            arguments.zone,
            arguments.instance,
            {RUNNING},
            timeout=arguments.timeout,
            poll_interval=arguments.poll_interval,
        )
        outcome = "started"
    else:
        raise LifecycleError(
            f"Compute Engine instance is in ambiguous state {initial}; "
            "Cloudmake will not issue a competing lifecycle operation"
        )
    profile = instance_profile(value, arguments.zone)
    publish(arguments.output, {"schema": 1, "resource_state": outcome, **profile})
    arguments.state_file.parent.mkdir(parents=True, exist_ok=True)
    arguments.state_file.write_text(outcome + "\n", encoding="utf-8")
    return 0


def stop(arguments: argparse.Namespace) -> int:
    value = describe(
        arguments.gcloud, arguments.project, arguments.zone, arguments.instance
    )
    initial = value["status"]
    if initial == "TERMINATED":
        outcome = "stopped"
    elif initial == "SUSPENDED":
        outcome = "suspended"
    elif initial == RUNNING:
        provider(
            arguments.gcloud,
            [
                "compute",
                "instances",
                "stop",
                arguments.instance,
                "--project",
                arguments.project,
                "--zone",
                arguments.zone,
                "--quiet",
            ],
            operation="instance stop",
        )
        value = wait_for(
            arguments.gcloud,
            arguments.project,
            arguments.zone,
            arguments.instance,
            {"TERMINATED"},
            timeout=arguments.timeout,
            poll_interval=arguments.poll_interval,
        )
        outcome = "stopped"
    elif initial in STOPPING:
        value = wait_for(
            arguments.gcloud,
            arguments.project,
            arguments.zone,
            arguments.instance,
            {"TERMINATED", "SUSPENDED"},
            timeout=arguments.timeout,
            poll_interval=arguments.poll_interval,
        )
        outcome = "stopped" if value["status"] == "TERMINATED" else "suspended"
    else:
        raise LifecycleError(
            f"Compute Engine instance is in ambiguous state {initial}; "
            "Cloudmake will not issue a competing stop"
        )
    publish(
        arguments.output,
        {
            "schema": 1,
            "resource_state": outcome,
            **instance_profile(value, arguments.zone),
        },
    )
    arguments.state_file.parent.mkdir(parents=True, exist_ok=True)
    arguments.state_file.write_text(outcome + "\n", encoding="utf-8")
    print(f"[gcp] instance={arguments.instance} resource={outcome} disk=retained")
    return 0


def status(arguments: argparse.Namespace) -> int:
    value = describe(
        arguments.gcloud, arguments.project, arguments.zone, arguments.instance
    )
    profile = instance_profile(value, arguments.zone)
    print(compact_context(profile))
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--gcloud", default="gcloud")
    result.add_argument("--project", required=True)
    result.add_argument("--zone", required=True)
    result.add_argument("--instance", required=True)
    result.add_argument("--output", type=Path, required=True)
    result.add_argument("--state-file", type=Path, required=True)
    result.add_argument("--timeout", type=float, default=300)
    result.add_argument("--poll-interval", type=float, default=5)
    actions = result.add_mutually_exclusive_group(required=True)
    actions.add_argument("--ensure-running", action="store_true")
    actions.add_argument("--stop", action="store_true")
    actions.add_argument("--status", action="store_true")
    return result


def main() -> int:
    arguments = parser().parse_args()
    if arguments.timeout <= 0 or arguments.poll_interval <= 0:
        raise LifecycleError("timeout and poll interval must be positive")
    if arguments.ensure_running:
        return ensure_running(arguments)
    if arguments.stop:
        return stop(arguments)
    return status(arguments)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except LifecycleError as error:
        print(f"cloudmake: {error}", file=sys.stderr)
        raise SystemExit(2)
