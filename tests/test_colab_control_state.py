from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest

from conftest import PROJECT_ROOT


TOOL = PROJECT_ROOT / "tools" / "colab_control_state.py"


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_remote_probe_ignores_jupyter_kernel_arguments(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    module = load("colab_control_state_jupyter")
    monkeypatch.setattr(module, "OWNER", tmp_path / "owner.json")
    monkeypatch.setattr(module, "FINGERPRINT", tmp_path / "source.sha256")
    module.OWNER.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(
        module.sys,
        "argv",
        ["ipykernel_launcher.py", "-f", "/tmp/kernel-connection.json"],
    )

    assert module.main() == 0
    assert (
        capsys.readouterr().out.strip()
        == "[cloudmake] control-state owner=present fingerprint=absent"
    )


def test_host_receipt_parser_remains_strict(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = load("colab_control_state_strict")
    receipt = tmp_path / "receipt.txt"
    receipt.write_text(
        "[cloudmake] control-state owner=present fingerprint=present\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        module.sys,
        "argv",
        ["colab_control_state.py", "--parse", str(receipt), "--field", "owner", "--typo"],
    )

    with pytest.raises(SystemExit) as error:
        module.main()
    assert error.value.code == 2
