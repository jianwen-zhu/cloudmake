from __future__ import annotations

import shutil
from pathlib import Path

from conftest import PROJECT_ROOT, run_command


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
    runtime_suffixes = {".conf", ".ipynb", ".mk", ".py", ".sh"}
    expected = {Path("Makefile"), Path("VERSION")}
    expected.update(
        path.relative_to(PROJECT_ROOT)
        for root in (PROJECT_ROOT / "core", PROJECT_ROOT / "backend")
        for path in root.rglob("*")
        if path.is_file()
        and (path.suffix in runtime_suffixes or path.name == "README.md")
    )
    installed = {
        path.relative_to(runtime) for path in runtime.rglob("*") if path.is_file()
    }
    assert installed == expected

    version = run_command([launcher, "--version"], cwd=tmp_path)
    assert version.stdout.strip() == f"cloudmake {(PROJECT_ROOT / 'VERSION').read_text().strip()}"

    backends = run_command([launcher, "--backends"], cwd=tmp_path)
    assert "colab-notebook" in backends.stdout
    assert "host-ssh" in backends.stdout

    template = run_command(
        [launcher, "--host-template", "generic"], cwd=tmp_path
    )
    assert "Host cloudmake-host" in template.stdout
    assert "StrictHostKeyChecking no" not in template.stdout

    project = sample_project(tmp_path)
    dry_run = run_command([launcher, "-C", project, "--sync-dry-run"], cwd=tmp_path)
    assert "Makefile" in dry_run.stdout


def test_source_layout_uses_ownership_roots() -> None:
    for legacy in (
        "bin",
        "backends",
        "host-templates",
        "notebooks",
        "tools",
        "transports",
    ):
        assert not (PROJECT_ROOT / legacy).exists()

    assert (PROJECT_ROOT / "cmd" / "cloudmake").is_file()
    assert (PROJECT_ROOT / "core" / "ssh.mk").is_file()
    assert (PROJECT_ROOT / "tests" / "fixtures" / "hello" / "Makefile").is_file()
    for backend in (
        "codespaces-ssh",
        "colab-notebook",
        "colab-ssh",
        "host-ssh",
        "kaggle-notebook",
        "lightning-studio-ssh",
        "local",
    ):
        assert (PROJECT_ROOT / "backend" / backend / "backend.mk").is_file()
