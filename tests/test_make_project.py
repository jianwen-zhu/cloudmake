from __future__ import annotations

import shutil
from pathlib import Path

from conftest import PROJECT_ROOT, run_command


def sample_project(tmp_path: Path) -> Path:
    project = tmp_path / "sample"
    (project / "src").mkdir(parents=True)
    shutil.copy2(PROJECT_ROOT / "Makefile.build", project / "Makefile")
    shutil.copy2(PROJECT_ROOT / "src" / "main.c", project / "src" / "main.c")
    return project


def make(project: Path, target: str, **variables: Path | str):
    assignments = [f"{name}={value}" for name, value in variables.items()]
    return run_command(["make", *assignments, target], cwd=project)


def test_sample_makefile_build_test_run_package_and_clean(tmp_path: Path) -> None:
    project = sample_project(tmp_path)
    build = tmp_path / "persistent-build"
    output = tmp_path / "remote-output"

    make(project, "build", BUILD_DIR=build, OUTPUT_DIR=output)
    assert (build / "hello").is_file()

    make(project, "test", BUILD_DIR=build, OUTPUT_DIR=output)
    run = make(project, "run", BUILD_DIR=build, OUTPUT_DIR=output)
    assert "remote build is working" in run.stdout

    make(project, "package", BUILD_DIR=build, OUTPUT_DIR=output)
    assert (output / "hello").read_bytes() == (build / "hello").read_bytes()

    make(project, "clean", BUILD_DIR=build, OUTPUT_DIR=output)
    assert not build.exists()
    assert not output.exists()


def test_sample_makefile_reuses_unchanged_objects(tmp_path: Path) -> None:
    project = sample_project(tmp_path)
    build = tmp_path / "build"
    make(project, "build", BUILD_DIR=build)
    object_file = build / "main.o"
    program = build / "hello"
    before = (object_file.stat().st_mtime_ns, program.stat().st_mtime_ns)

    second = make(project, "build", BUILD_DIR=build)
    after = (object_file.stat().st_mtime_ns, program.stat().st_mtime_ns)

    assert before == after
    assert "Nothing to be done" in second.stdout or "is up to date" in second.stdout


def test_install_copies_a_self_contained_runtime(tmp_path: Path) -> None:
    destination = tmp_path / "install-root"
    prefix = "/usr/local"
    run_command(
        ["make", "install", f"DESTDIR={destination}", f"PREFIX={prefix}"],
        cwd=PROJECT_ROOT,
    )

    launcher = destination / "usr" / "local" / "bin" / "cloudmake"
    runtime = destination / "usr" / "local" / "libexec" / "cloudmake"
    assert launcher.is_file()
    for relative in (
        "Makefile",
        "VERSION",
        "backends/colab-notebook.mk",
        "core/resilience.mk",
        "notebooks/colab.ipynb",
        "tools/source_fingerprint.py",
        "transports/ssh.mk",
    ):
        assert (runtime / relative).is_file()

    version = run_command([launcher, "--version"], cwd=tmp_path)
    assert version.stdout.strip() == f"cloudmake {(PROJECT_ROOT / 'VERSION').read_text().strip()}"

    project = sample_project(tmp_path)
    dry_run = run_command([launcher, "-C", project, "--sync-dry-run"], cwd=tmp_path)
    assert "Makefile" in dry_run.stdout
