from __future__ import annotations

from pathlib import Path
import shutil

from conftest import PROJECT_ROOT, run_command


FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "persistent-workspace"


def copy_fixture(tmp_path: Path) -> Path:
    project = tmp_path / "persistent-workspace"
    shutil.copytree(FIXTURE, project)
    return project


def test_fixture_is_an_ordinary_make_project_without_cloudmake_contract(
    tmp_path: Path,
) -> None:
    project = copy_fixture(tmp_path)
    makefile = (project / "Makefile").read_text(encoding="utf-8")

    assert "CLOUDMAKE" not in makefile
    for target in ("provision", "run", "advance", "clean"):
        assert f"{target}:" in makefile


def test_fixture_generated_state_is_incremental_and_executable(tmp_path: Path) -> None:
    project = copy_fixture(tmp_path)

    first = run_command(["make", "run", "advance"], cwd=project)
    second = run_command(["make", "run", "advance"], cwd=project)

    assert "workspace:hello" in first.stdout
    assert "generation:1" in first.stdout
    assert "generation:2" in second.stdout
    assert (project / ".workspace-state" / "generation").read_text() == "2\n"
    assert (project / "results" / "hello.txt").read_text() == "workspace:hello\n"
