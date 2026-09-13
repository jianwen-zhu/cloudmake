from __future__ import annotations

import argparse
import json
import subprocess
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="Report one Lightning Studio status")
    parser.add_argument("--client", required=True)
    parser.add_argument("--teamspace", required=True)
    parser.add_argument("--name", required=True)
    arguments = parser.parse_args()

    result = subprocess.run(
        [
            arguments.client,
            "studio",
            "list",
            "--teamspace",
            arguments.teamspace,
            "--json",
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if result.returncode:
        sys.stdout.write(result.stdout)
        return result.returncode
    try:
        studios = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        print(
            f"[cloudmake] invalid Lightning Studio status response: {error}",
            file=sys.stderr,
        )
        return 2
    if not isinstance(studios, list) or not all(
        isinstance(item, dict) for item in studios
    ):
        print("[cloudmake] invalid Lightning Studio status response shape", file=sys.stderr)
        return 2
    for studio in studios:
        if studio.get("name") == arguments.name:
            print(json.dumps(studio, sort_keys=True))
            return 0
    print(f"{arguments.name}: not found")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
