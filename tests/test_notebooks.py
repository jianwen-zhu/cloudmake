from __future__ import annotations

import base64
import io
import json
import shutil
import tarfile
from pathlib import Path

import pytest

from conftest import PROJECT_ROOT


COLAB_NOTEBOOK = PROJECT_ROOT / "notebooks" / "colab.ipynb"
KAGGLE_NOTEBOOK = PROJECT_ROOT / "notebooks" / "kaggle.ipynb"


def load_notebook(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def execute_code_cells(notebook: dict, replacements: dict[str, str]) -> dict:
    namespace: dict = {"__name__": "__cloudmake_notebook_test__"}
    for index, cell in enumerate(notebook["cells"]):
        if cell["cell_type"] != "code":
            continue
        source = cell.get("source", [])
        code = source if isinstance(source, str) else "".join(source)
        for old, new in replacements.items():
            code = code.replace(old, new)
        exec(compile(code, f"notebook-cell-{index}", "exec"), namespace)
    return namespace


def copy_sample_project(destination: Path) -> None:
    (destination / "src").mkdir(parents=True)
    shutil.copy2(PROJECT_ROOT / "Makefile.build", destination / "Makefile.build")
    shutil.copy2(PROJECT_ROOT / "src" / "main.c", destination / "src" / "main.c")


def source_archive() -> bytes:
    memory = io.BytesIO()
    with tarfile.open(fileobj=memory, mode="w:gz") as archive:
        archive.add(PROJECT_ROOT / "Makefile.build", arcname="Makefile.build")
        archive.add(PROJECT_ROOT / "src", arcname="src")
    return memory.getvalue()


def test_notebooks_are_structured_human_readable_notebooks() -> None:
    for path in (COLAB_NOTEBOOK, KAGGLE_NOTEBOOK):
        notebook = load_notebook(path)
        assert notebook["nbformat"] == 4
        assert notebook["nbformat_minor"] >= 0
        assert sum(cell["cell_type"] == "markdown" for cell in notebook["cells"]) >= 3
        assert sum(cell["cell_type"] == "code" for cell in notebook["cells"]) >= 3
        assert all("cell_type" in cell and "source" in cell for cell in notebook["cells"])


def test_notebooks_expose_the_same_target_contract_without_credentials() -> None:
    for path, backend in (
        (COLAB_NOTEBOOK, "colab-notebook"),
        (KAGGLE_NOTEBOOK, "kaggle-notebook"),
    ):
        serialized = path.read_text(encoding="utf-8")
        assert "CONVENTIONAL_TARGETS" not in serialized
        assert "run_make(REQUESTED_TARGET)" in serialized
        assert "COLLECT_DIR" in serialized
        assert "CLOUD_BACKEND=" not in serialized
        assert "BUILD_DIR=" not in serialized
        assert "OUTPUT_DIR=" not in serialized
        assert "MAKEFILE" in serialized
        assert "github.com" not in serialized.lower()
        assert "gist" not in serialized.lower()
        assert "token" not in serialized.lower()
        assert "private key" not in serialized.lower()


@pytest.mark.parametrize("target", ["build", "test", "run", "package"])
def test_colab_notebook_executes_each_make_target(tmp_path: Path, target: str) -> None:
    remote = tmp_path / "colab" / "workspace"
    source = remote / "src"
    copy_sample_project(source)
    control = tmp_path / "colab" / "target"
    control.parent.mkdir(parents=True, exist_ok=True)
    control.write_text(
        f"{base64.urlsafe_b64encode(target.encode()).decode()}\n3\n", encoding="utf-8"
    )

    namespace = execute_code_cells(
        load_notebook(COLAB_NOTEBOOK),
        {
            "/content/.cloud-build/workspace": str(remote),
            "/content/.cloud-build/artifacts.tar.gz": str(remote / "artifacts.tar.gz"),
            "/content/cloud-build-target": str(control),
        },
    )

    assert namespace["REQUESTED_TARGET"] == target
    assert (remote / "src" / "build" / "hello").is_file()
    assert not (remote / "artifacts.tar.gz").exists()


def test_colab_notebook_collects_artifacts_only_when_explicitly_requested(
    tmp_path: Path,
) -> None:
    remote = tmp_path / "colab" / "workspace"
    source = remote / "src"
    source.mkdir(parents=True)
    (source / "Makefile.build").write_text(
        ".PHONY: export-release\n"
        "export-release:\n"
        "\t@mkdir -p dist\n"
        "\t@printf exported > dist/hello\n",
        encoding="utf-8",
    )
    (remote / "output").mkdir(parents=True)
    (remote / "output" / "stale.txt").write_text("stale", encoding="utf-8")
    control = tmp_path / "colab" / "target"
    control.parent.mkdir(parents=True, exist_ok=True)
    control.write_text(
        f"{base64.urlsafe_b64encode(b'export-release').decode()}\n3\nMakefile.build\nW10=\n{base64.urlsafe_b64encode(b'dist').decode()}\n",
        encoding="utf-8",
    )

    execute_code_cells(
        load_notebook(COLAB_NOTEBOOK),
        {
            "/content/.cloud-build/workspace": str(remote),
            "/content/.cloud-build/artifacts.tar.gz": str(remote / "artifacts.tar.gz"),
            "/content/cloud-build-target": str(control),
        },
    )

    artifact = remote / "artifacts.tar.gz"
    assert artifact.is_file()
    with tarfile.open(artifact, "r:gz") as archive:
        names = {name.removeprefix("./") for name in archive.getnames()}
        assert "hello" in names
        assert "stale.txt" not in names


def test_colab_collect_removes_stale_artifact_before_a_failing_target(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    remote = tmp_path / "colab" / "workspace"
    source = remote / "src"
    source.mkdir(parents=True)
    (source / "Makefile").write_text(
        "fail:\n\t@printf 'project failure detail\\n' >&2; false\n",
        encoding="utf-8",
    )
    artifact = remote / "artifacts.tar.gz"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_bytes(b"stale")
    control = tmp_path / "colab" / "target"
    control.parent.mkdir(parents=True, exist_ok=True)
    control.write_text(
        f"{base64.urlsafe_b64encode(b'fail').decode()}\n1\nMakefile\nW10=\nLg==\n",
        encoding="utf-8",
    )

    namespace = execute_code_cells(
        load_notebook(COLAB_NOTEBOOK),
        {
            "/content/.cloud-build/workspace": str(remote),
            "/content/.cloud-build/artifacts.tar.gz": str(artifact),
            "/content/cloud-build-target": str(control),
        },
    )

    output = capsys.readouterr().out
    assert "project failure detail" in output
    assert "CalledProcessError" not in output
    assert namespace["TARGET_EXIT_CODE"] == 2
    assert json.loads((remote.parent / "target-result.json").read_text(encoding="utf-8")) == {
        "schema": 1,
        "target": "fail",
        "exit_code": 2,
    }
    assert not artifact.exists()


def test_colab_notebook_keeps_unexpected_setup_exceptions_diagnosable(
    tmp_path: Path,
) -> None:
    remote = tmp_path / "colab" / "workspace"
    (remote / "src").mkdir(parents=True)
    control = tmp_path / "colab" / "invalid-target"
    control.write_text("invalid\ncontrol\nfile\n", encoding="utf-8")

    with pytest.raises(ValueError, match="invalid cloudmake control file"):
        execute_code_cells(
            load_notebook(COLAB_NOTEBOOK),
            {
                "/content/.cloud-build/workspace": str(remote),
                "/content/cloud-build-target": str(control),
            },
        )


def test_colab_notebook_executes_project_specific_target(tmp_path: Path) -> None:
    remote = tmp_path / "colab" / "workspace"
    source = remote / "src"
    source.mkdir(parents=True)
    (source / "Makefile.build").write_text(
        ".PHONY: deploy\n"
        "deploy:\n"
        "\t@mkdir -p deployed\n"
        "\t@touch deployed/marker\n",
        encoding="utf-8",
    )
    control = tmp_path / "colab" / "target"
    control.write_text(
        f"{base64.urlsafe_b64encode(b'deploy').decode()}\n1\n", encoding="utf-8"
    )

    execute_code_cells(
        load_notebook(COLAB_NOTEBOOK),
        {
            "/content/.cloud-build/workspace": str(remote),
            "/content/cloud-build-target": str(control),
        },
    )
    assert (source / "deployed" / "marker").is_file()


@pytest.mark.parametrize("target", ["build", "test", "run", "package"])
def test_kaggle_notebook_executes_each_make_target(tmp_path: Path, target: str) -> None:
    root = tmp_path / "kaggle" / "build"
    working = tmp_path / "kaggle" / "working"
    working.mkdir(parents=True)
    encoded = base64.b64encode(source_archive()).decode("ascii")

    namespace = execute_code_cells(
        load_notebook(KAGGLE_NOTEBOOK),
        {
            "__SOURCE_ARCHIVE_B64__": encoded,
            "__REQUESTED_TARGET_B64__": base64.urlsafe_b64encode(target.encode()).decode(),
            "__JOBS__": "2",
            "__MAKEFILE_B64__": base64.urlsafe_b64encode(b"Makefile.build").decode(),
            "__PROJECT_ARGUMENTS_B64__": base64.urlsafe_b64encode(b"[]").decode(),
            "__COLLECT_DIR_B64__": "",
            "/tmp/cloud-build": str(root),
            "/kaggle/working": str(working),
        },
    )

    assert namespace["REQUESTED_TARGET"] == target
    assert (root / "src" / "build" / "hello").is_file()
    assert (working / "cloud-build.log").is_file()
    assert not (working / "artifacts.tar.gz").exists()


def test_kaggle_notebook_collects_artifacts_only_when_explicitly_requested(
    tmp_path: Path,
) -> None:
    root = tmp_path / "kaggle" / "build"
    working = tmp_path / "kaggle" / "working"
    working.mkdir(parents=True)

    execute_code_cells(
        load_notebook(KAGGLE_NOTEBOOK),
        {
            "__SOURCE_ARCHIVE_B64__": base64.b64encode(source_archive()).decode("ascii"),
            "__REQUESTED_TARGET_B64__": base64.urlsafe_b64encode(b"package").decode(),
            "__JOBS__": "2",
            "__MAKEFILE_B64__": base64.urlsafe_b64encode(b"Makefile.build").decode(),
            "__PROJECT_ARGUMENTS_B64__": base64.urlsafe_b64encode(b"[]").decode(),
            "__COLLECT_DIR_B64__": base64.urlsafe_b64encode(b"output").decode(),
            "/tmp/cloud-build": str(root),
            "/kaggle/working": str(working),
        },
    )

    artifact = working / "artifacts.tar.gz"
    assert artifact.is_file()
    with tarfile.open(artifact, "r:gz") as archive:
        assert "hello" in {name.removeprefix("./") for name in archive.getnames()}


def test_kaggle_notebook_data_filter_rejects_path_traversal(tmp_path: Path) -> None:
    memory = io.BytesIO()
    with tarfile.open(fileobj=memory, mode="w:gz") as archive:
        info = tarfile.TarInfo("../escape.txt")
        payload = b"unsafe"
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))
    root = tmp_path / "kaggle" / "build"
    working = tmp_path / "kaggle" / "working"
    working.mkdir(parents=True)

    with pytest.raises((tarfile.TarError, OSError, ValueError)):
        execute_code_cells(
            load_notebook(KAGGLE_NOTEBOOK),
            {
                "__SOURCE_ARCHIVE_B64__": base64.b64encode(memory.getvalue()).decode("ascii"),
                "__REQUESTED_TARGET_B64__": base64.urlsafe_b64encode(b"build").decode(),
                "__JOBS__": "1",
                "__MAKEFILE_B64__": base64.urlsafe_b64encode(b"Makefile.build").decode(),
                "__PROJECT_ARGUMENTS_B64__": base64.urlsafe_b64encode(b"[]").decode(),
                "__COLLECT_DIR_B64__": "",
                "/tmp/cloud-build": str(root),
                "/kaggle/working": str(working),
            },
        )
    assert not (tmp_path / "kaggle" / "escape.txt").exists()
