from __future__ import annotations

import argparse
import fcntl
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path


def holder(path: Path) -> str:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return "unknown holder"
    return (
        f"pid {value.get('pid', '?')} on {value.get('hostname', '?')} "
        f"running {value.get('command', '?')}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one command under a cloudmake lock")
    parser.add_argument("--path", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    arguments = parser.parse_args()
    command = arguments.command
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("a command is required after --")

    arguments.path.parent.mkdir(parents=True, exist_ok=True)
    with arguments.path.open("a+", encoding="utf-8") as stream:
        deadline = time.monotonic() + arguments.timeout
        while True:
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    print(
                        f"[cloudmake] timed out waiting for {arguments.path}: "
                        f"{holder(arguments.path)}",
                        file=sys.stderr,
                    )
                    return 75
                time.sleep(0.1)

        record = {
            "schema": 1,
            "pid": os.getpid(),
            "hostname": socket.gethostname(),
            "started": time.time(),
            "command": " ".join(command),
        }
        stream.seek(0)
        stream.truncate()
        json.dump(record, stream, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())

        try:
            return subprocess.run(command, check=False).returncode
        except KeyboardInterrupt:
            return 130


if __name__ == "__main__":
    raise SystemExit(main())
