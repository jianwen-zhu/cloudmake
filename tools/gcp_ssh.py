#!/usr/bin/env python3
"""OpenSSH-compatible edge adapter for ``gcloud compute ssh``.

The common SSH transport and rsync invoke a conventional remote-shell command.
This adapter preserves that surface without writing to ~/.ssh/config or
handling Google credentials itself.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shlex
import stat
import subprocess
import sys


class AdapterError(RuntimeError):
    pass


def create_wrapper(arguments: argparse.Namespace) -> int:
    if arguments.control_directory is not None:
        try:
            arguments.control_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            metadata = arguments.control_directory.lstat()
        except OSError as error:
            raise AdapterError(
                f"cannot prepare SSH control directory: {error}"
            ) from error
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or stat.S_ISLNK(metadata.st_mode)
            or metadata.st_uid != os.getuid()
        ):
            raise AdapterError(
                "SSH control directory is not a safe user-owned directory"
            )
        arguments.control_directory.chmod(0o700)
    command = [
        arguments.python,
        str(Path(__file__).resolve()),
        "--gcloud",
        arguments.gcloud,
        "--project",
        arguments.project,
        "--zone",
        arguments.zone,
        "--instance",
        arguments.instance,
    ]
    if arguments.tunnel_through_iap:
        command.append("--tunnel-through-iap")
    source = (
        "#!/bin/sh\nexec "
        + " ".join(shlex.quote(item) for item in command)
        + ' -- "$@"\n'
    )
    arguments.create_wrapper.parent.mkdir(parents=True, exist_ok=True)
    temporary = arguments.create_wrapper.with_suffix(".tmp")
    temporary.write_text(source, encoding="utf-8")
    temporary.chmod(0o700)
    temporary.replace(arguments.create_wrapper)
    return 0


def split_ssh(arguments: list[str], expected_host: str) -> tuple[list[str], list[str]]:
    ssh_options: list[str] = []
    index = 0
    options_with_value = {
        "-B",
        "-b",
        "-c",
        "-D",
        "-E",
        "-e",
        "-F",
        "-I",
        "-i",
        "-J",
        "-L",
        "-l",
        "-m",
        "-O",
        "-o",
        "-p",
        "-Q",
        "-R",
        "-S",
        "-W",
        "-w",
    }
    while index < len(arguments) and arguments[index].startswith("-"):
        option = arguments[index]
        ssh_options.append(option)
        index += 1
        if option in options_with_value:
            if index >= len(arguments):
                raise AdapterError(f"SSH option {option} requires a value")
            ssh_options.append(arguments[index])
            index += 1
    if index >= len(arguments):
        raise AdapterError("remote-shell invocation did not provide a host")
    host = arguments[index]
    if host != expected_host:
        raise AdapterError(
            f"remote-shell host {host!r} does not match GCP instance {expected_host!r}"
        )
    return ssh_options, arguments[index + 1 :]


def execute(arguments: argparse.Namespace, remainder: list[str]) -> int:
    ssh_options, remote = split_ssh(remainder, arguments.instance)
    command = [
        arguments.gcloud,
        "compute",
        "ssh",
        arguments.instance,
        "--project",
        arguments.project,
        "--zone",
        arguments.zone,
        "--quiet",
    ]
    if arguments.tunnel_through_iap:
        command.append("--tunnel-through-iap")
    if remote:
        # The common transport deliberately passes compound shell programs as
        # one argument. Preserve those verbatim; rsync instead supplies an argv
        # vector that must be quoted into one remote command string.
        remote_command = remote[0] if len(remote) == 1 else shlex.join(remote)
        command.extend(["--command", remote_command])
    if ssh_options:
        command.extend(["--", *ssh_options])
    return subprocess.run(command, check=False).returncode


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(add_help=False)
    result.add_argument("--gcloud", default="gcloud")
    result.add_argument("--project", required=True)
    result.add_argument("--zone", required=True)
    result.add_argument("--instance", required=True)
    result.add_argument("--tunnel-through-iap", action="store_true")
    result.add_argument("--create-wrapper", type=Path)
    result.add_argument("--control-directory", type=Path)
    result.add_argument("--python", default=sys.executable)
    return result


def main() -> int:
    selected, remainder = parser().parse_known_args()
    if selected.create_wrapper is not None:
        if remainder:
            raise AdapterError("wrapper creation does not accept SSH arguments")
        return create_wrapper(selected)
    if remainder[:1] == ["--"]:
        remainder = remainder[1:]
    return execute(selected, remainder)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AdapterError as error:
        print(f"cloudmake: {error}", file=sys.stderr)
        raise SystemExit(2)
