from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Iterable, Mapping

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def run_command(
    arguments: Iterable[os.PathLike[str] | str],
    *,
    cwd: Path,
    env: Mapping[str, str] | None = None,
    check: bool = True,
    timeout: float = 30,
) -> subprocess.CompletedProcess[str]:
    merged_environment = os.environ.copy()
    if env:
        merged_environment.update(env)
    result = subprocess.run(
        [os.fspath(argument) for argument in arguments],
        cwd=cwd,
        env=merged_environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
    )
    if check and result.returncode:
        raise AssertionError(
            f"command exited {result.returncode}: {list(arguments)!r}\n{result.stdout}"
        )
    return result


def write_executable(path: Path, source: str) -> Path:
    path.write_text(source, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


@pytest.fixture
def prototype(tmp_path: Path) -> Path:
    destination = tmp_path / "prototype"
    shutil.copytree(
        PROJECT_ROOT,
        destination,
        ignore=shutil.ignore_patterns(
            ".cloud-state", "artifacts", "build", "*_output.ipynb", "__pycache__"
        ),
    )
    return destination


@pytest.fixture
def fake_bin(tmp_path: Path) -> Path:
    directory = tmp_path / "bin"
    directory.mkdir()
    return directory


@pytest.fixture
def command_runner():
    return run_command


@pytest.fixture
def executable_writer():
    return write_executable

