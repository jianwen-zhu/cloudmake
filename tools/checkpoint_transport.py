#!/usr/bin/env python3
"""Create and consume one-operation checkpoint-key envelopes on a remote VM."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


PRIVATE_NAME = "private.pem"
PUBLIC_NAME = "public.pem"
ENVELOPE_NAME = "key.envelope"
RESULT = Path("/content/.cloud-build/checkpoint-transport-result.json")


def atomic_result(operation: str, status: str, error: str | None = None) -> None:
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{RESULT.name}.", suffix=".tmp", dir=RESULT.parent
    )
    temporary = Path(temporary_name)
    payload = {"schema": 1, "operation": operation, "status": status}
    if error:
        payload["error"] = error
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, sort_keys=True)
            stream.write("\n")
        os.chmod(temporary, 0o600)
        os.replace(temporary, RESULT)
    finally:
        temporary.unlink(missing_ok=True)


def require_openssl() -> str:
    executable = shutil.which("openssl")
    if executable is None:
        raise RuntimeError("checkpoint key transport requires openssl")
    return executable


def safe_directory(value: Path) -> Path:
    path = value.resolve()
    if path != Path("/content/.cloud-build/checkpoint-transport"):
        raise RuntimeError("refusing unsafe checkpoint transport directory")
    return path


def destroy(directory: Path) -> None:
    for name in (ENVELOPE_NAME, PRIVATE_NAME, PUBLIC_NAME):
        (directory / name).unlink(missing_ok=True)
    try:
        directory.rmdir()
    except FileNotFoundError:
        pass
    except OSError:
        if any(directory.iterdir()):
            raise RuntimeError("checkpoint transport directory contains unknown files")


def generate(directory: Path) -> None:
    openssl = require_openssl()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(directory, 0o700)
    destroy(directory)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    private_key = directory / PRIVATE_NAME
    public_key = directory / PUBLIC_NAME
    subprocess.run(
        [
            openssl,
            "genpkey",
            "-quiet",
            "-algorithm",
            "RSA",
            "-pkeyopt",
            "rsa_keygen_bits:3072",
            "-out",
            os.fspath(private_key),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    os.chmod(private_key, 0o600)
    subprocess.run(
        [
            openssl,
            "pkey",
            "-in",
            os.fspath(private_key),
            "-pubout",
            "-out",
            os.fspath(public_key),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    os.chmod(public_key, 0o600)
    print("[cloudmake] checkpoint-transport-key=ready")


def password(directory: Path) -> None:
    if sys.stdout.isatty():
        raise RuntimeError("checkpoint key plaintext may only be written to a pipe")
    openssl = require_openssl()
    private_key = directory / PRIVATE_NAME
    envelope = directory / ENVELOPE_NAME
    if not private_key.is_file() or not envelope.is_file():
        raise RuntimeError("checkpoint key envelope is incomplete")
    result = subprocess.run(
        [
            openssl,
            "pkeyutl",
            "-decrypt",
            "-inkey",
            os.fspath(private_key),
            "-in",
            os.fspath(envelope),
            "-pkeyopt",
            "rsa_padding_mode:oaep",
            "-pkeyopt",
            "rsa_oaep_md:sha256",
            "-pkeyopt",
            "rsa_mgf1_md:sha256",
        ],
        check=False,
        stdout=sys.stdout.buffer,
        stderr=subprocess.DEVNULL,
    )
    if result.returncode != 0:
        raise RuntimeError("checkpoint key envelope decryption failed")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", nargs="?", choices=("generate", "password", "destroy"))
    parser.add_argument("--directory", type=Path, default=Path("/content/.cloud-build/checkpoint-transport"))
    if os.environ.get("CLOUDMAKE_CHECKPOINT_TRANSPORT_OPERATION"):
        operation = os.environ["CLOUDMAKE_CHECKPOINT_TRANSPORT_OPERATION"]
        directory = safe_directory(Path("/content/.cloud-build/checkpoint-transport"))
    else:
        args = parser.parse_args()
        operation = args.operation
        directory = safe_directory(args.directory)
    if operation in {"generate", "destroy"}:
        RESULT.unlink(missing_ok=True)
        try:
            if operation == "generate":
                generate(directory)
            else:
                destroy(directory)
                print("[cloudmake] checkpoint-transport-key=destroyed")
            atomic_result(operation, "succeeded")
        except BaseException as error:
            atomic_result(operation, "failed", str(error) or type(error).__name__)
            raise
    elif operation == "password":
        password(directory)
    else:
        parser.error("operation is required")


if __name__ == "__main__":
    main()
