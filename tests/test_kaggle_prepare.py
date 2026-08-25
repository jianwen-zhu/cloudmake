from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from conftest import PROJECT_ROOT, run_command


SCRIPT = PROJECT_ROOT / "tools" / "kaggle_prepare.py"
TEMPLATE = PROJECT_ROOT / "notebooks" / "kaggle.ipynb"


def prepare(
    tmp_path: Path,
    *,
    accelerator: str = "",
    private: str = "true",
    internet: str = "false",
    collect_dir: str = "",
):
    archive = tmp_path / "source.tar.gz"
    archive.write_bytes(b"test archive payload")
    owner = tmp_path / "owner.json"
    owner.write_text(
        json.dumps(
            {
                "schema": 1,
                "project_id": "project-id",
                "project_name": "sample",
                "source_path": "/tmp/sample",
                "hostname": "test-host",
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "runner.ipynb"
    metadata = tmp_path / "kernel-metadata.json"
    result = run_command(
        [
            "python3",
            SCRIPT,
            "--template",
            TEMPLATE,
            "--archive",
            archive,
            "--owner",
            owner,
            "--output",
            output,
            "--metadata",
            metadata,
            "--kernel-ref",
            "tester/cloudmake-job",
            "--title",
            "Cloudmake job",
            "--target",
            "test",
            "--jobs",
            "7",
            "--private",
            private,
            "--enable-internet",
            internet,
            "--collect-dir-b64",
            base64.urlsafe_b64encode(collect_dir.encode()).decode() if collect_dir else "",
            "--accelerator",
            accelerator,
        ],
        cwd=tmp_path,
        check=False,
    )
    return result, archive, output, metadata


def test_prepare_embeds_archive_and_replaces_control_tokens(tmp_path: Path) -> None:
    result, archive, output, metadata = prepare(tmp_path, accelerator="NvidiaL4")

    assert result.returncode == 0, result.stdout
    notebook = json.loads(output.read_text(encoding="utf-8"))
    serialized = json.dumps(notebook)
    assert base64.b64encode(archive.read_bytes()).decode("ascii") in serialized
    assert "__SOURCE_ARCHIVE_B64__" not in serialized
    assert "__REQUESTED_TARGET_B64__" not in serialized
    assert "__JOBS__" not in serialized
    assert "__MAKEFILE_B64__" not in serialized
    assert "__PROJECT_ARGUMENTS_B64__" not in serialized
    assert "__COLLECT_DIR_B64__" not in serialized
    assert base64.urlsafe_b64encode(b"test").decode("ascii") in serialized
    assert "'7'" in serialized
    assert all(cell.get("outputs", []) == [] for cell in notebook["cells"] if cell["cell_type"] == "code")
    assert all(cell.get("execution_count") is None for cell in notebook["cells"] if cell["cell_type"] == "code")
    assert metadata.exists()
    assert notebook["metadata"]["cloudmake"]["project_id"] == "project-id"


def test_prepare_embeds_explicit_artifact_collection_directory(tmp_path: Path) -> None:
    result, _, output, _ = prepare(tmp_path, collect_dir="dist/release")

    assert result.returncode == 0, result.stdout
    encoded = base64.urlsafe_b64encode(b"dist/release").decode()
    assert f"COLLECT_DIR_B64 = '{encoded}'" in output.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("accelerator", "gpu", "tpu"),
    [("", False, False), ("NvidiaTeslaT4", True, False), ("NvidiaL4", True, False), ("TpuV6E8", False, True)],
)
def test_prepare_writes_provider_metadata(
    tmp_path: Path, accelerator: str, gpu: bool, tpu: bool
) -> None:
    result, _, output, metadata_path = prepare(tmp_path, accelerator=accelerator)
    assert result.returncode == 0, result.stdout

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata == {
        "id": "tester/cloudmake-job",
        "title": "Cloudmake job",
        "code_file": output.name,
        "language": "python",
        "kernel_type": "notebook",
        "is_private": True,
        "enable_gpu": gpu,
        "enable_tpu": tpu,
        "enable_internet": False,
        "machine_shape": accelerator,
        "dataset_sources": [],
        "competition_sources": [],
        "kernel_sources": [],
        "model_sources": [],
    }


@pytest.mark.parametrize("value", ["true", "TRUE", "yes", "1", "on"])
def test_prepare_accepts_true_boolean_spellings(tmp_path: Path, value: str) -> None:
    result, _, _, metadata = prepare(tmp_path, private=value)
    assert result.returncode == 0, result.stdout
    assert json.loads(metadata.read_text(encoding="utf-8"))["is_private"] is True


def test_prepare_rejects_invalid_boolean_and_unsafe_makefile(tmp_path: Path) -> None:
    result, _, _, _ = prepare(tmp_path, private="perhaps")
    assert result.returncode == 2
    assert "expected a boolean value" in result.stdout

    archive = tmp_path / "archive"
    archive.write_bytes(b"x")
    invalid = run_command(
        [
            "python3", SCRIPT, "--template", TEMPLATE, "--archive", archive,
            "--owner", tmp_path / "missing-owner.json",
            "--output", tmp_path / "out.ipynb", "--metadata", tmp_path / "metadata.json",
            "--kernel-ref", "a/b", "--title", "title", "--target", "deploy",
            "--makefile", "../Makefile",
            "--jobs", "1", "--private", "true", "--enable-internet", "false",
        ],
        cwd=tmp_path,
        check=False,
    )
    assert invalid.returncode == 2
    assert "safe relative values" in invalid.stdout
