"""Bound a Colab CLI process independently of the kernel execution timeout."""

from __future__ import annotations

import argparse
import math
import os
import signal
import subprocess
import sys


def terminate_process_group(process: subprocess.Popen) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


def handle_termination(signum: int, _frame: object) -> None:
    raise SystemExit(128 + signum)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, required=True)
    parser.add_argument("client", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("--timeout must be a finite positive number")
    command = args.client
    if command[:1] == ["--"]:
        command = command[1:]
    if not command:
        parser.error("a client command is required")

    signal.signal(signal.SIGTERM, handle_termination)
    signal.signal(signal.SIGHUP, handle_termination)
    try:
        process = subprocess.Popen(
            command, stdin=subprocess.DEVNULL, start_new_session=True
        )
    except OSError:
        print("[colab] Could not start the configured client.", file=sys.stderr)
        return 1
    try:
        code = process.wait(timeout=args.timeout)
    except subprocess.TimeoutExpired:
        terminate_process_group(process)
        print(
            f"[colab] Local Colab client exceeded its {args.timeout:g}s deadline.",
            file=sys.stderr,
        )
        return 124
    except BaseException:
        terminate_process_group(process)
        raise
    # Reserve 124 for the local watchdog so callers can distinguish it.
    if code == 124:
        return 1
    return code if code >= 0 else 128 - code


if __name__ == "__main__":
    raise SystemExit(main())
