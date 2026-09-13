from __future__ import annotations

import argparse
import base64
import json
import shlex
import sys
from pathlib import PurePosixPath


def decode_arguments(value: str) -> list[str]:
    try:
        payload = base64.urlsafe_b64decode(value.encode("ascii"))
        arguments = json.loads(payload.decode("utf-8"))
    except Exception as error:
        raise ValueError("project arguments are not valid encoded JSON") from error
    if not isinstance(arguments, list) or not all(
        isinstance(argument, str) for argument in arguments
    ):
        raise ValueError("project arguments must be a JSON string list")
    return arguments


def environment_arguments(value: str) -> list[str]:
    values = decode_arguments(value)
    for item in values:
        if "=" not in item or "\0" in item or "\n" in item:
            raise ValueError("Dev Container environment is invalid")
    return values


def decode_json(value: str, description: str):
    try:
        payload = base64.urlsafe_b64decode(value.encode("ascii"))
        return json.loads(payload.decode("utf-8"))
    except Exception as error:
        raise ValueError(f"{description} is not valid encoded JSON") from error


def main() -> int:
    parser = argparse.ArgumentParser(description="Construct a quoted remote Make command")
    parser.add_argument("--source", required=True)
    parser.add_argument("--makefile", required=True)
    parser.add_argument("--jobs", type=int, required=True)
    parser.add_argument("--target", default="")
    parser.add_argument("--target-b64", default="")
    parser.add_argument("--arguments-b64", default="W10=")
    parser.add_argument("--runner", choices=("native", "oci"), default="native")
    parser.add_argument("--oci-image-b64", default="")
    parser.add_argument("--oci-devices-b64", default="W10=")
    parser.add_argument("--oci-runtimes-b64", default="W10=")
    parser.add_argument("--environment-b64", default="W10=")
    parser.add_argument("--host-requirements-b64", default="e30=")
    parser.add_argument("--forward-ports-b64", default="W10=")
    parser.add_argument("--devcontainer-tool", default="")
    parser.add_argument("--oci-runtime", default="auto")
    parser.add_argument("--oci-tool", default="")
    parser.add_argument("--oci-cache", default="")
    parser.add_argument("--oci-result", default="")
    parser.add_argument("--python", default="python3")
    arguments = parser.parse_args()

    if arguments.jobs < 1:
        parser.error("--jobs must be positive")
    if bool(arguments.target) == bool(arguments.target_b64):
        parser.error("exactly one of --target and --target-b64 is required")
    if arguments.target_b64:
        try:
            target = base64.b64decode(
                arguments.target_b64.encode("ascii"), altchars=b"-_", validate=True
            ).decode("utf-8")
        except Exception as error:
            parser.error(f"invalid --target-b64: {error}")
    else:
        target = arguments.target
    if not target or "\n" in target:
        parser.error("--target must be a non-empty single-line name")
    makefile = PurePosixPath(arguments.makefile)
    if not arguments.makefile or makefile.is_absolute() or ".." in makefile.parts:
        parser.error("--makefile must be a safe relative path")

    try:
        project_arguments = decode_arguments(arguments.arguments_b64)
        environment = environment_arguments(arguments.environment_b64)
        forward_ports = decode_json(
            arguments.forward_ports_b64, "Dev Container forward ports"
        )
        if not isinstance(forward_ports, list):
            raise ValueError("Dev Container forward ports must be a list")
    except ValueError as error:
        print(f"cloudmake: {error}", file=sys.stderr)
        return 2

    if arguments.runner == "native":
        environment_prefix = ["env", *environment] if environment else []
        command = [
            *environment_prefix,
            "make",
            "-C",
            arguments.source,
            "-f",
            arguments.makefile,
            *project_arguments,
            f"-j{arguments.jobs}",
            "--",
            target,
        ]
    else:
        missing = [
            option
            for option, value in (
                ("--oci-image-b64", arguments.oci_image_b64),
                ("--oci-tool", arguments.oci_tool),
                ("--oci-cache", arguments.oci_cache),
                ("--oci-result", arguments.oci_result),
            )
            if not value
        ]
        if missing:
            parser.error("OCI runner requires " + ", ".join(missing))
        try:
            image = base64.b64decode(
                arguments.oci_image_b64.encode("ascii"), altchars=b"-_", validate=True
            ).decode("utf-8")
            devices = decode_arguments(arguments.oci_devices_b64)
            runtimes = decode_arguments(arguments.oci_runtimes_b64)
        except Exception as error:
            parser.error(f"invalid encoded OCI selection: {error}")
        command = [
            arguments.python,
            arguments.oci_tool,
            "--mode",
            "run",
            "--image",
            image,
            "--runtime",
            arguments.oci_runtime,
            "--source",
            arguments.source,
            "--cache",
            arguments.oci_cache,
            "--makefile",
            arguments.makefile,
            "--target-b64",
            arguments.target_b64
            or base64.urlsafe_b64encode(target.encode("utf-8")).decode("ascii"),
            "--arguments-b64",
            arguments.arguments_b64,
            "--jobs",
            str(arguments.jobs),
            "--result",
            arguments.oci_result,
        ]
        for device in devices:
            command.extend(["--device", device])
        for runtime in runtimes:
            command.extend(["--runtime-candidate", runtime])
        for value in environment:
            command.extend(["--env", value])
        for item in forward_ports:
            if not isinstance(item, dict) or not isinstance(item.get("port"), int):
                parser.error("invalid encoded Dev Container forward ports")
            command.extend(["--forward-port", str(item["port"])])
        if arguments.host_requirements_b64 != "e30=":
            command.extend(
                ["--host-requirements-b64", arguments.host_requirements_b64]
            )
    commands: list[list[str]] = []
    if arguments.host_requirements_b64 != "e30=":
        if not arguments.devcontainer_tool:
            parser.error("host requirements require --devcontainer-tool")
        commands.append(
            [
                arguments.python,
                arguments.devcontainer_tool,
                "--check-host",
                arguments.host_requirements_b64,
                "--workspace",
                arguments.source,
            ]
        )
    commands.append(command)
    print(" && ".join(shlex.join(item) for item in commands))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
