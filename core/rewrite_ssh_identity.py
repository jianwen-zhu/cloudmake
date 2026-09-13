from __future__ import annotations

import argparse
import shlex
from pathlib import Path


def rewrite(contents: str, identity: Path) -> str:
    replacement = f"      IdentityFile {shlex.quote(str(identity.expanduser()))}"
    output: list[str] = []
    replaced = False
    for line in contents.splitlines():
        fields = shlex.split(line, comments=True)
        if fields and fields[0].lower() == "identityfile":
            if replaced:
                raise ValueError(
                    "provider SSH configuration has multiple IdentityFile directives"
                )
            output.append(replacement)
            replaced = True
        else:
            output.append(line)
    if not replaced:
        raise ValueError("provider SSH configuration has no IdentityFile directive")
    return "\n".join(output) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reference a selected key in provider SSH configuration"
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--identity", type=Path, required=True)
    arguments = parser.parse_args()
    arguments.output.write_text(
        rewrite(arguments.input.read_text(encoding="utf-8"), arguments.identity),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
