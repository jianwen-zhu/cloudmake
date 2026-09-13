from __future__ import annotations

import json
import sys
from pathlib import Path

from conftest import PROJECT_ROOT, run_command


TOOL = PROJECT_ROOT / "tools" / "target_result.py"


def test_target_result_propagates_expected_make_failure_without_traceback(
    tmp_path: Path,
) -> None:
    result_path = tmp_path / "target-result.json"
    result_path.write_text(
        json.dumps({"schema": 1, "target": "gemm", "exit_code": 2}),
        encoding="utf-8",
    )

    result = run_command(
        [sys.executable, TOOL, "--result", result_path],
        cwd=tmp_path,
        check=False,
    )

    assert result.returncode == 2
    assert result.stdout.strip() == "[cloudmake] target 'gemm' failed with exit status 2"
    assert "Traceback" not in result.stdout
    assert "CalledProcessError" not in result.stdout


def test_target_result_classifies_invalid_receipt_as_infrastructure_failure(
    tmp_path: Path,
) -> None:
    result_path = tmp_path / "target-result.json"
    result_path.write_text("not-json", encoding="utf-8")

    result = run_command(
        [sys.executable, TOOL, "--result", result_path],
        cwd=tmp_path,
        check=False,
    )

    assert result.returncode == 1
    assert "[cloudmake] infrastructure failure:" in result.stdout
    assert "target result" in result.stdout
