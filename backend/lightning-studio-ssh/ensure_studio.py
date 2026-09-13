from __future__ import annotations

import argparse
import json
import subprocess
import sys


def invoke(
    client: str, arguments: list[str], *, echo: bool = True
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [client, *arguments],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if echo and result.stdout:
        sys.stdout.write(result.stdout)
    return result


def normalized(value: object) -> str:
    return str(value or "").rsplit(".", 1)[-1].upper()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Start or reconcile one Lightning Studio"
    )
    parser.add_argument("--client", required=True)
    parser.add_argument("--teamspace", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--machine", required=True)
    arguments = parser.parse_args()

    listed = invoke(
        arguments.client,
        ["studio", "list", "--teamspace", arguments.teamspace, "--json"],
        echo=False,
    )
    if listed.returncode:
        return listed.returncode
    try:
        studios = json.loads(listed.stdout)
    except json.JSONDecodeError as error:
        print(
            f"[cloudmake] invalid Lightning Studio list response: {error}",
            file=sys.stderr,
        )
        return 2
    if not isinstance(studios, list) or not all(
        isinstance(item, dict) for item in studios
    ):
        print("[cloudmake] invalid Lightning Studio list response shape", file=sys.stderr)
        return 2
    studio = next(
        (item for item in studios if item.get("name") == arguments.name), None
    )

    common = ["--name", arguments.name, "--teamspace", arguments.teamspace]
    if studio is not None and normalized(studio.get("status")) == "RUNNING":
        if normalized(studio.get("machine")) == normalized(arguments.machine):
            print(
                f"[cloudmake] Lightning Studio {arguments.name} is already running "
                f"on {arguments.machine}."
            )
            return 0
        result = invoke(
            arguments.client,
            ["studio", "switch", *common, "--machine", arguments.machine],
        )
        return result.returncode

    result = invoke(
        arguments.client,
        ["studio", "start", *common, "--machine", arguments.machine, "--create"],
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
