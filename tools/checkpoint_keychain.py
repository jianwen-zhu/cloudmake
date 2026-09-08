#!/usr/bin/env python3
"""Manage Cloudmake-owned checkpoint keys without exposing plaintext.

The command's stdout is status-only. Repository keys exist in the operating
system credential store and transient process memory; encryption emits only an
RSA-OAEP envelope suitable for upload to a remote checkpoint helper.
"""

from __future__ import annotations

import argparse
import ctypes
import os
from pathlib import Path
import platform
import re
import secrets
import shutil
import subprocess
import tempfile
from typing import Protocol


PROJECT_KEY = re.compile(r"^[0-9a-f]{24}$")
ACCOUNT = "checkpoint-v1"
SERVICE_PREFIX = "org.cloudmake.checkpoint"
ERR_SEC_ITEM_NOT_FOUND = -25300


class CredentialStore(Protocol):
    def find(self, service: str, account: str) -> bytearray | None: ...

    def add(self, service: str, account: str, secret: bytearray) -> None: ...

    def delete(self, service: str, account: str) -> bool: ...


class MacOSKeychain:
    """Minimal Security.framework generic-password adapter."""

    def __init__(self) -> None:
        security = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/Security.framework/Security"
        )
        security.SecKeychainFindGenericPassword.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
        ]
        security.SecKeychainFindGenericPassword.restype = ctypes.c_int32
        security.SecKeychainAddGenericPassword.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        security.SecKeychainAddGenericPassword.restype = ctypes.c_int32
        security.SecKeychainItemFreeContent.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        security.SecKeychainItemFreeContent.restype = ctypes.c_int32
        security.SecKeychainItemDelete.argtypes = [ctypes.c_void_p]
        security.SecKeychainItemDelete.restype = ctypes.c_int32
        core_foundation = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
        )
        core_foundation.CFRelease.argtypes = [ctypes.c_void_p]
        core_foundation.CFRelease.restype = None
        self.security = security
        self.core_foundation = core_foundation

    @staticmethod
    def _buffer(value: str | bytearray) -> tuple[ctypes.Array[ctypes.c_char], int]:
        encoded = value.encode("utf-8") if isinstance(value, str) else bytes(value)
        return ctypes.create_string_buffer(encoded), len(encoded)

    def find(self, service: str, account: str) -> bytearray | None:
        service_buffer, service_length = self._buffer(service)
        account_buffer, account_length = self._buffer(account)
        secret_length = ctypes.c_uint32()
        secret_pointer = ctypes.c_void_p()
        item = ctypes.c_void_p()
        status = self.security.SecKeychainFindGenericPassword(
            None,
            service_length,
            service_buffer,
            account_length,
            account_buffer,
            ctypes.byref(secret_length),
            ctypes.byref(secret_pointer),
            ctypes.byref(item),
        )
        if status == ERR_SEC_ITEM_NOT_FOUND:
            return None
        if status != 0:
            raise RuntimeError(
                "macOS Keychain checkpoint-key lookup failed; refusing to "
                f"create or replace a key (status {status})"
            )
        try:
            return bytearray(ctypes.string_at(secret_pointer, secret_length.value))
        finally:
            self.security.SecKeychainItemFreeContent(None, secret_pointer)
            if item:
                self.core_foundation.CFRelease(item)

    def add(self, service: str, account: str, secret: bytearray) -> None:
        service_buffer, service_length = self._buffer(service)
        account_buffer, account_length = self._buffer(account)
        secret_buffer, secret_length = self._buffer(secret)
        status = self.security.SecKeychainAddGenericPassword(
            None,
            service_length,
            service_buffer,
            account_length,
            account_buffer,
            secret_length,
            secret_buffer,
            None,
        )
        ctypes.memset(secret_buffer, 0, len(secret_buffer))
        if status != 0:
            raise RuntimeError(f"macOS Keychain creation failed with status {status}")

    def delete(self, service: str, account: str) -> bool:
        service_buffer, service_length = self._buffer(service)
        account_buffer, account_length = self._buffer(account)
        item = ctypes.c_void_p()
        status = self.security.SecKeychainFindGenericPassword(
            None,
            service_length,
            service_buffer,
            account_length,
            account_buffer,
            None,
            None,
            ctypes.byref(item),
        )
        if status == ERR_SEC_ITEM_NOT_FOUND:
            return False
        if status != 0:
            raise RuntimeError(
                "macOS Keychain checkpoint-key lookup failed before deletion "
                f"(status {status})"
            )
        try:
            status = self.security.SecKeychainItemDelete(item)
            if status != 0:
                raise RuntimeError("macOS Keychain checkpoint-key deletion failed")
            return True
        finally:
            if item:
                self.core_foundation.CFRelease(item)


class SecretServiceStore:
    """Linux Secret Service adapter using secret-tool's stdin contract."""

    def __init__(self) -> None:
        executable = shutil.which("secret-tool")
        if executable is None:
            raise RuntimeError(
                "Linux checkpointing requires secret-tool and a Secret Service"
            )
        self.executable = executable

    def find(self, service: str, account: str) -> bytearray | None:
        result = subprocess.run(
            [
                self.executable,
                "lookup",
                "service",
                service,
                "account",
                account,
            ],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if result.returncode == 1 and not result.stdout and not result.stderr:
            return None
        if result.returncode != 0:
            raise RuntimeError(
                "Secret Service checkpoint-key lookup failed; refusing to "
                "create or replace a key"
            )
        return bytearray(result.stdout.rstrip(b"\n"))

    def add(self, service: str, account: str, secret: bytearray) -> None:
        result = subprocess.run(
            [
                self.executable,
                "store",
                f"--label=Cloudmake checkpoint {service.rsplit('.', 1)[-1]}",
                "service",
                service,
                "account",
                account,
            ],
            input=secret,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        if result.returncode != 0:
            raise RuntimeError("Secret Service rejected the checkpoint key")

    def delete(self, service: str, account: str) -> bool:
        existing = self.find(service, account)
        if existing is None:
            return False
        wipe(existing)
        result = subprocess.run(
            [
                self.executable,
                "clear",
                "service",
                service,
                "account",
                account,
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        if result.returncode != 0:
            raise RuntimeError("Secret Service checkpoint-key deletion failed")
        return True


def credential_store() -> CredentialStore:
    system = platform.system()
    if system == "Darwin":
        return MacOSKeychain()
    if system == "Linux":
        return SecretServiceStore()
    raise RuntimeError(
        f"checkpoint credential storage is not implemented for {system}"
    )


def check_store(store: CredentialStore) -> None:
    probe = store.find(f"{SERVICE_PREFIX}.{'0' * 24}", ACCOUNT)
    wipe(probe)


def service_name(project_key: str) -> str:
    if not PROJECT_KEY.fullmatch(project_key):
        raise ValueError("project key must be 24 lowercase hexadecimal characters")
    return f"{SERVICE_PREFIX}.{project_key}"


def wipe(secret: bytearray | None) -> None:
    if secret is not None:
        for index in range(len(secret)):
            secret[index] = 0


def validate_key(secret: bytearray) -> None:
    if len(secret) < 32:
        raise RuntimeError(
            "checkpoint repository key in the operating-system credential "
            "store is malformed; refusing to replace it"
        )


def ensure_key(store: CredentialStore, project_key: str) -> str:
    service = service_name(project_key)
    existing = store.find(service, ACCOUNT)
    if existing is not None:
        try:
            validate_key(existing)
        finally:
            wipe(existing)
        return "reused"
    generated = bytearray(secrets.token_urlsafe(32), "ascii")
    try:
        store.add(service, ACCOUNT, generated)
    finally:
        wipe(generated)
    return "created"


def delete_key(store: CredentialStore, project_key: str) -> str:
    return "deleted" if store.delete(service_name(project_key), ACCOUNT) else "absent"


def encrypt_key(
    store: CredentialStore,
    project_key: str,
    public_key: Path,
    output: Path,
) -> None:
    service = service_name(project_key)
    secret = store.find(service, ACCOUNT)
    if secret is None:
        raise RuntimeError(
            "checkpoint repository key is missing from the operating-system "
            "credential store; refusing to create a replacement"
        )
    try:
        validate_key(secret)
    except BaseException:
        wipe(secret)
        raise
    if public_key.is_symlink() or not public_key.is_file():
        wipe(secret)
        raise RuntimeError("checkpoint transport public key is unavailable")
    openssl = shutil.which("openssl")
    if openssl is None:
        wipe(secret)
        raise RuntimeError("checkpoint key transport requires openssl")
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output.name}.", suffix=".tmp", dir=output.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            result = subprocess.run(
                [
                    openssl,
                    "pkeyutl",
                    "-encrypt",
                    "-pubin",
                    "-inkey",
                    os.fspath(public_key),
                    "-pkeyopt",
                    "rsa_padding_mode:oaep",
                    "-pkeyopt",
                    "rsa_oaep_md:sha256",
                    "-pkeyopt",
                    "rsa_mgf1_md:sha256",
                ],
                input=secret,
                stdout=stream,
                stderr=subprocess.PIPE,
                check=False,
            )
        if result.returncode != 0:
            raise RuntimeError("checkpoint key envelope encryption failed")
        os.replace(temporary, output)
    finally:
        wipe(secret)
        temporary.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="operation", required=True)
    subparsers.add_parser("check")
    ensure = subparsers.add_parser("ensure")
    ensure.add_argument("--project-key", required=True)
    encrypt = subparsers.add_parser("encrypt")
    encrypt.add_argument("--project-key", required=True)
    encrypt.add_argument("--public-key", type=Path, required=True)
    encrypt.add_argument("--output", type=Path, required=True)
    delete = subparsers.add_parser("delete")
    delete.add_argument("--project-key", required=True)
    args = parser.parse_args()

    store = credential_store()
    if args.operation == "check":
        check_store(store)
        print("[cloudmake] checkpoint-key-store=ready")
    elif args.operation == "ensure":
        outcome = ensure_key(store, args.project_key)
        print(f"[cloudmake] checkpoint-key={outcome} store=os-credential-store")
    elif args.operation == "encrypt":
        encrypt_key(store, args.project_key, args.public_key, args.output)
        print("[cloudmake] checkpoint-key-envelope=ready")
    else:
        outcome = delete_key(store, args.project_key)
        print(f"[cloudmake] checkpoint-key={outcome} store=os-credential-store")


if __name__ == "__main__":
    main()
