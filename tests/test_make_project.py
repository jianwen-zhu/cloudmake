from __future__ import annotations

import shutil
from pathlib import Path

from conftest import PROJECT_ROOT, run_command


CORE_RUNTIME_SUFFIXES = {".mk", ".py", ".sh"}
BACKEND_RUNTIME_SUFFIXES = {
    ".mk",
    ".py",
    ".sh",
    ".ipynb",
    ".conf",
    ".json",
    ".Dockerfile",
}


def sample_project(tmp_path: Path) -> Path:
    project = tmp_path / "sample"
    (project / "src").mkdir(parents=True)
    fixture = PROJECT_ROOT / "tests" / "fixtures" / "hello"
    shutil.copy2(fixture / "Makefile", project / "Makefile")
    shutil.copy2(fixture / "src" / "main.c", project / "src" / "main.c")
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


def test_source_layout_exposes_ownership_without_legacy_roots() -> None:
    assert (PROJECT_ROOT / "cmd" / "cloudmake").is_file()
    assert all(
        (directory / "backend.mk").is_file()
        for directory in (PROJECT_ROOT / "backend").iterdir()
        if directory.is_dir()
    )
    for legacy in (
        "bin",
        "backends",
        "transports",
        "tools",
        "notebooks",
        "host-templates",
    ):
        assert not (PROJECT_ROOT / legacy).exists()


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
    expected_runtime = {Path("Makefile"), Path("VERSION")}
    expected_runtime.update(
        path.relative_to(PROJECT_ROOT)
        for path in (PROJECT_ROOT / "core").iterdir()
        if path.is_file() and path.suffix in CORE_RUNTIME_SUFFIXES
    )
    expected_runtime.update(
        path.relative_to(PROJECT_ROOT)
        for path in (PROJECT_ROOT / "backend").glob("*/*")
        if path.is_file()
        and (path.suffix in BACKEND_RUNTIME_SUFFIXES or path.name == "README.md")
    )
    installed_runtime = {
        path.relative_to(runtime) for path in runtime.rglob("*") if path.is_file()
    }
    assert installed_runtime == expected_runtime

    version = run_command([launcher, "--version"], cwd=tmp_path)
    assert version.stdout.strip() == f"cloudmake {(PROJECT_ROOT / 'VERSION').read_text().strip()}"

    template = run_command(
        [launcher, "--host-template", "generic"], cwd=tmp_path
    )
    assert "Host cloudmake-host" in template.stdout
    assert "StrictHostKeyChecking no" not in template.stdout

    project = sample_project(tmp_path)
    dry_run = run_command([launcher, "-C", project, "--sync-dry-run"], cwd=tmp_path)
    assert "Makefile" in dry_run.stdout
