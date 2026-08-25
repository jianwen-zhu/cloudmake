from __future__ import annotations

import argparse
import os
import shlex
import sys
from pathlib import Path


def directives(path: Path) -> tuple[list[str], list[Path]]:
    hosts: list[str] = []
    identities: list[Path] = []
    for number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            fields = shlex.split(raw_line, comments=True)
        except ValueError as error:
            raise ValueError(f"{path}:{number}: invalid SSH configuration: {error}") from error
        if len(fields) < 2:
            continue
        name = fields[0].lower()
        if name == "host":
            hosts.extend(fields[1:])
        elif name == "identityfile":
            identities.extend(Path(value).expanduser() for value in fields[1:])
    return hosts, identities


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate generated Codespaces SSH configuration")
    parser.add_argument("config", type=Path)
    arguments = parser.parse_args()

    try:
        hosts, identities = directives(arguments.config)
    except (OSError, ValueError) as error:
        print(f"[cloudmake] {error}", file=sys.stderr)
        return 2

    if not hosts:
        print("[cloudmake] generated Codespaces SSH configuration has no Host alias", file=sys.stderr)
        return 2
    if not identities:
        print("[cloudmake] generated Codespaces SSH configuration has no IdentityFile", file=sys.stderr)
        return 2

    missing = [
        path
        for identity in identities
        for path in (identity, Path(f"{identity}.pub"))
        if not path.is_file() or not os.access(path, os.R_OK)
    ]
    if missing:
        identity = identities[0]
        print(
            "[cloudmake] generated Codespaces SSH configuration references "
            "missing or unreadable key files: " + ", ".join(map(str, missing)),
            file=sys.stderr,
        )
        print(
            "Create the dedicated key, then retry: "
            f"ssh-keygen -t ed25519 -f {shlex.quote(str(identity))} "
            "-N '' -C github-codespaces",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
