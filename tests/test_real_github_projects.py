from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from conftest import PROJECT_ROOT, run_command, write_executable


REAL_PROJECTS = PROJECT_ROOT / "tests" / "real_projects"
PREPARE = REAL_PROJECTS / "prepare.sh"
NVIDIA_OVERLAY = REAL_PROJECTS / "overlays" / "nvidia-cuda-cpp" / "Makefile"
GPU_MODE_OVERLAY = (
    REAL_PROJECTS / "overlays" / "gpu-mode-vector-addition" / "Makefile"
)
LAUNCHER = PROJECT_ROOT / "bin" / "cloudmake"


def install_fake_compiler(path: Path) -> Path:
    return write_executable(
        path,
        r'''#!/usr/bin/env python3
import sys
from pathlib import Path

arguments = sys.argv[1:]
output = Path(arguments[arguments.index("-o") + 1])
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text("#!/bin/sh\necho fake CUDA program: " + output.name + "\n", encoding="utf-8")
output.chmod(output.stat().st_mode | 0o100)
''',
    )


def synthetic_nvidia_project(tmp_path: Path) -> Path:
    project = tmp_path / "nvidia"
    sources = project / "Sources"
    sources.mkdir(parents=True)
    for name in ("cpu-cooling.cpp", "gpu-cooling.cpp", "thrust-cooling.cpp"):
        (sources / name).write_text("int main() { return 0; }\n", encoding="utf-8")
    shutil.copy2(NVIDIA_OVERLAY, project / "Makefile")
    return project


def synthetic_gpu_mode_project(tmp_path: Path) -> Path:
    project = tmp_path / "gpu-mode"
    project.mkdir()
    (project / "vector_addition.cu").write_text(
        "int main() { return 0; }\n", encoding="utf-8"
    )
    shutil.copy2(GPU_MODE_OVERLAY, project / "Makefile")
    return project


def test_nvidia_overlay_builds_runs_incrementally_and_cleans(tmp_path: Path) -> None:
    project = synthetic_nvidia_project(tmp_path)
    compiler = install_fake_compiler(tmp_path / "fake-compiler")
    variables = [f"CXX={compiler}", f"NVCC={compiler}"]

    first = run_command(["make", *variables, "run"], cwd=project)
    assert first.stdout.count("fake CUDA program:") == 3
    assert sorted(
        path.name for path in (project / "build").iterdir() if not path.name.startswith(".")
    ) == [
        "cpu-cooling",
        "gpu-cooling",
        "thrust-cooling",
    ]

    second = run_command(["make", *variables, "build"], cwd=project)
    assert "Nothing to be done" in second.stdout or "is up to date" in second.stdout

    run_command(["make", "clean"], cwd=project)
    assert not (project / "build").exists()


def test_gpu_mode_overlay_adds_a_runnable_incremental_target(tmp_path: Path) -> None:
    project = synthetic_gpu_mode_project(tmp_path)
    compiler = install_fake_compiler(tmp_path / "fake-nvcc")

    first = run_command(["make", f"NVCC={compiler}", "run"], cwd=project)
    assert "fake CUDA program: vector_addition" in first.stdout
    before = (
        (project / "vector_addition.o").stat().st_mtime_ns,
        (project / "vector_addition").stat().st_mtime_ns,
    )

    run_command(["make", f"NVCC={compiler}", "default"], cwd=project)
    after = (
        (project / "vector_addition.o").stat().st_mtime_ns,
        (project / "vector_addition").stat().st_mtime_ns,
    )
    assert after == before

    run_command(["make", "clean"], cwd=project)
    assert not (project / "vector_addition.o").exists()
    assert not (project / "vector_addition").exists()


@pytest.mark.real_github
@pytest.mark.skipif(
    os.environ.get("CLOUDMAKE_TEST_REAL_GITHUB") != "1",
    reason="set CLOUDMAKE_TEST_REAL_GITHUB=1 to clone pinned GitHub projects",
)
def test_pinned_github_projects_accept_and_run_the_overlays(tmp_path: Path) -> None:
    prepared = tmp_path / "real-projects"
    result = run_command([PREPARE, prepared], cwd=PROJECT_ROOT, timeout=180)
    nvidia_project, gpu_mode_project = map(Path, result.stdout.splitlines())
    compiler = install_fake_compiler(tmp_path / "fake-compiler")

    nvidia = run_command(
        ["make", f"CXX={compiler}", f"NVCC={compiler}", "run"],
        cwd=nvidia_project,
    )
    gpu_mode = run_command(
        ["make", f"NVCC={compiler}", "run"], cwd=gpu_mode_project
    )

    assert nvidia.stdout.count("fake CUDA program:") == 3
    assert "fake CUDA program: vector_addition" in gpu_mode.stdout


@pytest.mark.real_github
@pytest.mark.live_cloud
@pytest.mark.skipif(
    os.environ.get("CLOUDMAKE_TEST_LIVE_COLAB") != "1",
    reason="set CLOUDMAKE_TEST_LIVE_COLAB=1 to allocate real Colab GPU sessions",
)
def test_pinned_github_projects_run_on_colab_t4(tmp_path: Path) -> None:
    prepared = tmp_path / "real-projects"
    result = run_command([PREPARE, prepared], cwd=PROJECT_ROOT, timeout=180)
    projects = list(map(Path, result.stdout.splitlines()))

    for index, project in enumerate(projects, start=1):
        session = f"cloudmake-real-project-{os.getpid()}-{index}"
        environment = {
            "COLAB_SESSION": session,
            "CLOUDMAKE_STATE_HOME": str(tmp_path / "state"),
            "CLOUDMAKE_CACHE_HOME": str(tmp_path / "cache"),
            "CLOUDMAKE_CONFIG_HOME": str(tmp_path / "config"),
        }
        try:
            run_command(
                [LAUNCHER, "-b", "colab", "--gpu=T4", "run"],
                cwd=project,
                env=environment,
                timeout=1200,
            )
        finally:
            run_command(
                [LAUNCHER, "-b", "colab", "--stop"],
                cwd=project,
                env=environment,
                check=False,
                timeout=120,
            )


@pytest.mark.real_github
@pytest.mark.live_cloud
@pytest.mark.skipif(
    os.environ.get("CLOUDMAKE_TEST_LIVE_LIGHTNING") != "1",
    reason=(
        "set CLOUDMAKE_TEST_LIVE_LIGHTNING=1 to allocate a real Lightning T4 Studio"
    ),
)
def test_pinned_github_projects_run_on_lightning_t4(tmp_path: Path) -> None:
    required = ["LIGHTNING_STUDIO", "LIGHTNING_TEAMSPACE"]
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        pytest.fail("missing live Lightning settings: " + ", ".join(missing))

    prepared = tmp_path / "real-projects"
    result = run_command([PREPARE, prepared], cwd=PROJECT_ROOT, timeout=180)
    projects = list(map(Path, result.stdout.splitlines()))
    environment = {
        "CLOUDMAKE_STATE_HOME": str(tmp_path / "state"),
        "CLOUDMAKE_CACHE_HOME": str(tmp_path / "cache"),
        "CLOUDMAKE_CONFIG_HOME": str(tmp_path / "config"),
        # These two fixed regression paths may belong to a prior local gate run.
        "CLOUDMAKE_ADOPT": "1",
    }

    try:
        for project in projects:
            run_command(
                [LAUNCHER, "-b", "lightning", "--gpu=T4", "run"],
                cwd=project,
                env=environment,
                timeout=1200,
            )
    finally:
        run_command(
            [LAUNCHER, "-b", "lightning", "--stop"],
            cwd=projects[0],
            env=environment,
            check=False,
            timeout=180,
        )
