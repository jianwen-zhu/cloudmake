from __future__ import annotations

import argparse
import math
import re
import subprocess
import sys
import time


def positive_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return number


parser = argparse.ArgumentParser(description="Wait for a Kaggle notebook version")
parser.add_argument("--kaggle", required=True)
parser.add_argument("--kernel", required=True)
parser.add_argument("--timeout", type=positive_float, required=True)
parser.add_argument("--poll", type=positive_float, required=True)
arguments = parser.parse_args()

deadline = time.monotonic() + arguments.timeout
last_status = None

while time.monotonic() < deadline:
    remaining = deadline - time.monotonic()
    try:
        result = subprocess.run(
            [arguments.kaggle, "kernels", "status", arguments.kernel],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=min(30.0, remaining),
        )
        status = result.stdout.strip()
        returncode = result.returncode
    except subprocess.TimeoutExpired:
        status = "Kaggle status probe timed out"
        returncode = None
    normalized = status.lower()

    if status and status != last_status:
        print(status, flush=True)
        last_status = status

    if returncode == 0 and re.search(r"\bcomplete\b", normalized):
        raise SystemExit(0)
    if re.search(r"\b(error|cancelled|canceled|failed)\b", normalized):
        print("Kaggle notebook version did not complete successfully.", file=sys.stderr)
        raise SystemExit(1)

    remaining = deadline - time.monotonic()
    if remaining > 0:
        time.sleep(min(arguments.poll, remaining))

print(f"Timed out waiting for {arguments.kernel}", file=sys.stderr)
raise SystemExit(124)
