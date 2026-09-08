from __future__ import annotations

import sys
from pathlib import Path

import pytest

from conftest import PROJECT_ROOT, run_command


HELPER = PROJECT_ROOT / "tools" / "colab_control_state.py"


def test_remote_probe_accepts_injected_notebook_kernel_connection_file(
    tmp_path: Path,
) -> None:
    kernel = tmp_path / "kernel-123.json"
    kernel.write_text("{}\n", encoding="utf-8")

    result = run_command([sys.executable, HELPER, "-f", kernel], cwd=tmp_path)

    assert result.stdout.strip() == (
        "[cloudmake] control-state owner=absent fingerprint=absent"
    )


def test_local_receipt_parse_remains_strict_and_valid(tmp_path: Path) -> None:
    receipt = tmp_path / "control-state.txt"
    receipt.write_text(
        "kernel noise\n"
        "[cloudmake] control-state owner=present fingerprint=absent\n",
        encoding="utf-8",
    )

    result = run_command(
        [sys.executable, HELPER, "--parse", receipt, "--field", "owner"],
        cwd=tmp_path,
    )

    assert result.stdout.strip() == "present"


@pytest.mark.parametrize(
    "arguments",
    [
        ("--parse", "receipt.txt"),
        ("--field", "owner"),
        ("--parse", "receipt.txt", "--field", "invalid"),
        ("--parse", "receipt.txt", "--field", "owner", "-f", "kernel.json"),
    ],
)
def test_malformed_local_receipt_parse_is_rejected(
    tmp_path: Path, arguments: tuple[str, ...]
) -> None:
    result = run_command(
        [sys.executable, HELPER, *arguments], cwd=tmp_path, check=False
    )

    assert result.returncode == 2
    assert "error:" in result.stdout
