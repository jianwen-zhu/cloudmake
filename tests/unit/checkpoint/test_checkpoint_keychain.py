from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

from conftest import PROJECT_ROOT, run_command


KEYCHAIN_PATH = PROJECT_ROOT / "tools" / "checkpoint_keychain.py"
TRANSPORT_PATH = PROJECT_ROOT / "tools" / "checkpoint_transport.py"
PROJECT_KEY = "0123456789abcdef01234567"
SENTINEL = b"checkpoint-sentinel-secret-94fd61b7"


def load_keychain_module():
    spec = importlib.util.spec_from_file_location("checkpoint_keychain", KEYCHAIN_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeStore:
    def __init__(self, value: bytes | None = None) -> None:
        self.value = value
        self.added = 0

    def find(self, service: str, account: str) -> bytearray | None:
        del service, account
        return bytearray(self.value) if self.value is not None else None

    def add(self, service: str, account: str, secret: bytearray) -> None:
        del service, account
        self.value = bytes(secret)
        self.added += 1

    def delete(self, service: str, account: str) -> bool:
        del service, account
        existed = self.value is not None
        self.value = None
        return existed


def generate_transport_pair(tmp_path: Path) -> tuple[Path, Path]:
    private_key = tmp_path / "private.pem"
    public_key = tmp_path / "public.pem"
    subprocess.run(
        [
            "openssl",
            "genpkey",
            "-quiet",
            "-algorithm",
            "RSA",
            "-pkeyopt",
            "rsa_keygen_bits:2048",
            "-out",
            private_key,
        ],
        check=True,
    )
    subprocess.run(
        ["openssl", "pkey", "-in", private_key, "-pubout", "-out", public_key],
        check=True,
    )
    return private_key, public_key


def decrypt(private_key: Path, envelope: Path) -> bytes:
    return subprocess.run(
        [
            "openssl",
            "pkeyutl",
            "-decrypt",
            "-inkey",
            private_key,
            "-in",
            envelope,
            "-pkeyopt",
            "rsa_padding_mode:oaep",
            "-pkeyopt",
            "rsa_oaep_md:sha256",
            "-pkeyopt",
            "rsa_mgf1_md:sha256",
        ],
        check=True,
        stdout=subprocess.PIPE,
    ).stdout


def test_ensure_generates_once_and_reuses_without_printing() -> None:
    module = load_keychain_module()
    store = FakeStore()

    assert module.ensure_key(store, PROJECT_KEY) == "created"
    generated = store.value
    assert generated is not None and len(generated) >= 32
    assert store.added == 1
    assert module.ensure_key(store, PROJECT_KEY) == "reused"
    assert store.value == generated
    assert store.added == 1


def test_delete_removes_only_the_selected_cloudmake_key() -> None:
    module = load_keychain_module()
    store = FakeStore(SENTINEL)

    assert module.delete_key(store, PROJECT_KEY) == "deleted"
    assert store.value is None
    assert module.delete_key(store, PROJECT_KEY) == "absent"


def test_encrypt_emits_only_randomized_envelope(tmp_path: Path) -> None:
    module = load_keychain_module()
    private_key, public_key = generate_transport_pair(tmp_path)
    store = FakeStore(SENTINEL)
    first = tmp_path / "first.envelope"
    second = tmp_path / "second.envelope"

    module.encrypt_key(store, PROJECT_KEY, public_key, first)
    module.encrypt_key(store, PROJECT_KEY, public_key, second)

    assert SENTINEL not in first.read_bytes()
    assert SENTINEL not in second.read_bytes()
    assert first.read_bytes() != second.read_bytes()
    assert decrypt(private_key, first) == SENTINEL
    assert decrypt(private_key, second) == SENTINEL
    assert first.stat().st_mode & 0o077 == 0


def test_encrypt_plaintext_uses_only_local_openssl_stdin(
    tmp_path: Path, monkeypatch
) -> None:
    module = load_keychain_module()
    _, public_key = generate_transport_pair(tmp_path)
    real_run = module.subprocess.run
    calls = 0

    def guarded_run(command, **kwargs):
        nonlocal calls
        calls += 1
        serialized_arguments = b"\0".join(os.fsencode(value) for value in command)
        serialized_environment = b"\0".join(
            os.fsencode(f"{name}={value}")
            for name, value in (kwargs.get("env") or {}).items()
        )
        assert SENTINEL not in serialized_arguments
        assert SENTINEL not in serialized_environment
        assert bytes(kwargs["input"]) == SENTINEL
        return real_run(command, **kwargs)

    monkeypatch.setattr(module.subprocess, "run", guarded_run)
    module.encrypt_key(
        FakeStore(SENTINEL), PROJECT_KEY, public_key, tmp_path / "key.envelope"
    )

    assert calls == 1


def test_missing_key_fails_without_creating_replacement(tmp_path: Path) -> None:
    module = load_keychain_module()
    _, public_key = generate_transport_pair(tmp_path)
    store = FakeStore()

    try:
        module.encrypt_key(store, PROJECT_KEY, public_key, tmp_path / "key.envelope")
    except RuntimeError as error:
        assert "refusing to create a replacement" in str(error)
    else:
        raise AssertionError("missing checkpoint key was accepted")
    assert store.added == 0


def test_malformed_existing_key_fails_without_replacement(tmp_path: Path) -> None:
    module = load_keychain_module()
    _, public_key = generate_transport_pair(tmp_path)
    store = FakeStore(b"too-short")

    for operation in (
        lambda: module.ensure_key(store, PROJECT_KEY),
        lambda: module.encrypt_key(
            store, PROJECT_KEY, public_key, tmp_path / "key.envelope"
        ),
    ):
        try:
            operation()
        except RuntimeError as error:
            assert "malformed" in str(error)
        else:
            raise AssertionError("malformed checkpoint key was accepted")
    assert store.added == 0


def test_plaintext_is_absent_from_tool_source_and_process_routes(tmp_path: Path) -> None:
    contents = KEYCHAIN_PATH.read_bytes() + TRANSPORT_PATH.read_bytes()
    assert SENTINEL not in contents

    module = load_keychain_module()
    _, public_key = generate_transport_pair(tmp_path)
    envelope = tmp_path / "key.envelope"
    module.encrypt_key(FakeStore(SENTINEL), PROJECT_KEY, public_key, envelope)

    persisted = b"".join(
        path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file() and path.name != "private.pem"
    )
    assert SENTINEL not in persisted
    assert SENTINEL not in b"\0".join(os.fsencode(value) for value in os.environ.values())


def test_remote_password_refuses_a_terminal(monkeypatch, tmp_path: Path) -> None:
    source = TRANSPORT_PATH.read_text(encoding="utf-8")
    assert "sys.stdout.isatty()" in source
    assert "stderr=subprocess.DEVNULL" in source
    assert "stdout=sys.stdout.buffer" in source


def test_invalid_project_key_is_rejected() -> None:
    module = load_keychain_module()
    for value in ("", "../escape", "A" * 24, "a" * 23, "a" * 25):
        try:
            module.service_name(value)
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid project key accepted: {value!r}")


def test_secret_service_distinguishes_missing_item_from_store_failure(
    monkeypatch,
) -> None:
    module = load_keychain_module()
    monkeypatch.setattr(module.shutil, "which", lambda name: "/usr/bin/secret-tool")
    store = module.SecretServiceStore()

    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=1, stdout=b"", stderr=b""
        ),
    )
    assert store.find("service", "account") is None

    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=1, stdout=b"", stderr=b"keyring is locked\n"
        ),
    )
    try:
        store.find("service", "account")
    except RuntimeError as error:
        assert "refusing to create or replace" in str(error)
    else:
        raise AssertionError("Secret Service failure was treated as a missing key")


def test_credential_store_preflight_is_read_only() -> None:
    module = load_keychain_module()
    store = FakeStore(SENTINEL)

    module.check_store(store)

    assert store.value == SENTINEL
    assert store.added == 0


def test_macos_keychain_does_not_change_requesting_executable_identity() -> None:
    source = KEYCHAIN_PATH.read_text(encoding="utf-8")

    assert "SecKeychainFindGenericPassword" in source
    assert "SecKeychainItemDelete" in source
    assert '"find-generic-password"' not in source
    assert '"delete-generic-password"' not in source
