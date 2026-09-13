#!/usr/bin/env python3
"""Detect locally broken google-colab-cli execution dependencies."""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path


PROBE = r"""
import importlib.util
import sys

if importlib.util.find_spec("colab_cli") is None:
    raise SystemExit(0)

try:
    from colab_cli.runtime import ColabRuntime
except Exception as error:
    print(
        "[doctor] Incompatible Colab CLI execution environment: "
        f"the runtime module cannot be imported ({error}).",
        file=sys.stderr,
    )
    raise SystemExit(2)

try:
    ColabRuntime("https://example.invalid", "cloudmake-doctor").kernel_client
except AttributeError as error:
    if "KernelClient" in str(error):
        print(
            "[doctor] Incompatible Colab CLI execution environment: "
            f"the installed kernel client does not provide the API required by colab ({error}).",
            file=sys.stderr,
        )
        print(
            "[doctor] Reinstall a Cloudmake-qualified google-colab-cli dependency set; "
            "'colab version' and 'colab sessions' alone do not detect this failure.",
            file=sys.stderr,
        )
        raise SystemExit(2)
except Exception:
    # Constructing a future client may validate its placeholder URL or require
    # additional local arguments. Only the reproduced missing-API defect is a
    # release blocker here; authentication remains the provider probe's job.
    pass
"""


def launcher_python(command: str) -> list[str] | None:
    executable = shutil.which(command)
    if executable is None:
        return None

    try:
        first_line = Path(executable).read_bytes().splitlines()[0].decode(
            "utf-8", errors="strict"
        )
    except (IndexError, OSError, UnicodeDecodeError):
        return None

    if not first_line.startswith("#!"):
        return None

    try:
        words = shlex.split(first_line[2:].strip())
    except ValueError:
        return None
    if not words:
        return None

    if os.path.basename(words[0]) != "env":
        return words

    arguments = words[1:]
    if arguments[:1] == ["-S"]:
        arguments = arguments[1:]
    while arguments and (arguments[0].startswith("-") or "=" in arguments[0]):
        arguments = arguments[1:]
    if not arguments:
        return None
    interpreter = shutil.which(arguments[0])
    if interpreter is None:
        return None
    return [interpreter, *arguments[1:]]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--colab-bin", default="colab")
    arguments = parser.parse_args()

    interpreter = launcher_python(arguments.colab_bin)
    if interpreter is None:
        # The prerequisite gate already verified that the client is executable.
        # Unknown native launchers cannot be introspected without invoking a
        # provider operation, so leave them to the ordinary read-only probe.
        return 0

    completed = subprocess.run([*interpreter, "-c", PROBE], check=False)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
