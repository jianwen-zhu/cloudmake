from __future__ import annotations

import argparse
import json
import sys


def normalize(backend: str, output: str) -> str:
    value = output.lower()
    if any(fragment in value for fragment in ("failed", "failure", "error")):
        return "failed"
    if any(fragment in value for fragment in ("not found", "no active", "absent")):
        return "absent"
    if any(fragment in value for fragment in ("complete", "succeeded", "success")):
        return "succeeded" if backend == "kaggle-notebook" else "ready"
    if any(fragment in value for fragment in ("pending", "queued", "starting", "provisioning")):
        return "starting"
    if "running" in value:
        return "running" if backend == "kaggle-notebook" else "ready"
    if any(fragment in value for fragment in ("available", "ready", "active", "idle")):
        return "ready"
    if any(fragment in value for fragment in ("stopped", "shutdown", "inactive")):
        return "stopped"
    return "unknown"


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize provider status output")
    parser.add_argument("--backend", required=True)
    parser.add_argument("--json", action="store_true")
    arguments = parser.parse_args()
    raw = sys.stdin.read()
    status = normalize(arguments.backend, raw)
    if arguments.json:
        print(json.dumps({"backend": arguments.backend, "status": status}))
    else:
        print(f"[cloudmake] status={status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
