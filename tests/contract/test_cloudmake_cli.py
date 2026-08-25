from __future__ import annotations

import base64
import json
import os
from pathlib import Path

import pytest

from conftest import PROJECT_ROOT, run_command, write_executable


LAUNCHER = PROJECT_ROOT / "bin" / "cloudmake"

pytestmark = pytest.mark.contract


def make_project(path: Path) -> Path:
    path.mkdir(parents=True)
    (path / "Makefile").write_text(
        ".PHONY: build test run package clean fetch status\n"
        "build test run package clean fetch status:\n\t@true\n",
        encoding="utf-8",
    )
    (path / "source.txt").write_text("local source\n", encoding="utf-8")
    return path


def contract_environment(tmp_path: Path, fake_bin: Path) -> tuple[dict[str, str], Path]:
    log = tmp_path / "engine.jsonl"
    write_executable(
        fake_bin / "make",
        r'''#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path
with Path(os.environ["CLOUDMAKE_TEST_ENGINE_LOG"]).open("a", encoding="utf-8") as stream:
    stream.write(json.dumps(sys.argv[1:]) + "\n")
raise SystemExit(int(os.environ.get("CLOUDMAKE_TEST_ENGINE_EXIT", "0")))
''',
    )
    environment = {
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "CLOUDMAKE_CONFIG_HOME": str(tmp_path / "config"),
        "CLOUDMAKE_STATE_HOME": str(tmp_path / "state"),
        "CLOUDMAKE_CACHE_HOME": str(tmp_path / "cache"),
        "CLOUDMAKE_TEST_ENGINE_LOG": str(log),
    }
    return environment, log


def invoke(project: Path, environment: dict[str, str], *arguments: str, check: bool = True):
    return run_command(
        [LAUNCHER, *arguments], cwd=project, env=environment, check=check
    )


def engine_calls(log: Path) -> list[list[str]]:
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


def assert_assignment(call: list[str], name: str, value: str) -> None:
    assert f"{name}={value}" in call


def assert_remote_target(call: list[str], target: str) -> None:
    encoded = next(
        argument.split("=", 1)[1]
        for argument in call
        if argument.startswith("REMOTE_TARGET_B64=")
    )
    assert base64.urlsafe_b64decode(encoded).decode("utf-8") == target


def assert_collect_directory(call: list[str], directory: str) -> None:
    encoded = next(
        argument.split("=", 1)[1]
        for argument in call
        if argument.startswith("REMOTE_COLLECT_DIR_B64=")
    )
    assert base64.urlsafe_b64decode(encoded).decode("utf-8") == directory


def project_arguments(call: list[str]) -> list[str]:
    encoded = next(
        argument.split("=", 1)[1]
        for argument in call
        if argument.startswith("CLOUDMAKE_PROJECT_ARGS_B64=")
    )
    return json.loads(base64.urlsafe_b64decode(encoded).decode("utf-8"))


def test_no_arguments_is_read_only_and_does_not_invoke_engine(
    tmp_path: Path, fake_bin: Path
) -> None:
    project = make_project(tmp_path / "project")
    environment, log = contract_environment(tmp_path, fake_bin)

    result = invoke(project, environment)

    assert "project" in result.stdout
    assert "backend" in result.stdout.lower()
    assert engine_calls(log) == []


@pytest.mark.parametrize(
    "arguments",
    [("--version",), ("--backends",), ("--history",), ("--host-templates",)],
)
def test_information_commands_do_not_invoke_build_engine(
    tmp_path: Path, fake_bin: Path, arguments: tuple[str, ...]
) -> None:
    project = make_project(tmp_path / "project")
    environment, log = contract_environment(tmp_path, fake_bin)

    result = invoke(project, environment, *arguments)

    assert result.stdout.strip()
    assert engine_calls(log) == []


def test_installed_host_templates_are_listed_and_rendered_without_engine_use(
    tmp_path: Path, fake_bin: Path
) -> None:
    project = make_project(tmp_path / "project")
    environment, log = contract_environment(tmp_path, fake_bin)

    listed = invoke(project, environment, "--host-templates")
    rendered = invoke(
        project, environment, "--host-template", "oci-always-free"
    )

    assert "generic" in listed.stdout
    assert "oci-always-free" in listed.stdout
    assert "gcp-e2-micro" in listed.stdout
    assert "Host oci-free" in rendered.stdout
    assert "StrictHostKeyChecking no" not in rendered.stdout
    assert "PRIVATE KEY-----" not in rendered.stdout
    assert engine_calls(log) == []


def test_unknown_host_template_fails_without_engine_use(
    tmp_path: Path, fake_bin: Path
) -> None:
    project = make_project(tmp_path / "project")
    environment, log = contract_environment(tmp_path, fake_bin)

    result = invoke(
        project, environment, "--host-template", "unknown", check=False
    )

    assert result.returncode == 2
    assert "unknown SSH host template" in result.stdout
    assert engine_calls(log) == []


def test_doctor_invokes_read_only_backend_readiness_gate(
    tmp_path: Path, fake_bin: Path
) -> None:
    project = make_project(tmp_path / "project")
    environment, log = contract_environment(tmp_path, fake_bin)

    invoke(project, environment, "-b", "colab", "--doctor")

    call = engine_calls(log)[0]
    assert_assignment(call, "BACKEND", "colab-notebook")
    assert "doctor" in call
    assert "dispatch" not in call
    assert not any(argument.startswith("REMOTE_TARGET_B64=") for argument in call)


def test_use_persists_canonical_backend_outside_project(
    tmp_path: Path, fake_bin: Path
) -> None:
    project = make_project(tmp_path / "project")
    before = {path.relative_to(project) for path in project.rglob("*")}
    environment, log = contract_environment(tmp_path, fake_bin)

    invoke(project, environment, "--use", "colab", "--gpu=T4")
    invoke(project, environment, "build")

    after = {path.relative_to(project) for path in project.rglob("*")}
    assert after == before
    assert len(engine_calls(log)) == 1
    call = engine_calls(log)[0]
    assert_assignment(call, "PROJECT_DIR", str(project.resolve()))
    assert_assignment(call, "BACKEND", "colab-notebook")
    assert_assignment(call, "COLAB_GPU", "T4")
    assert_remote_target(call, "build")
    assert "dispatch" in call


def test_use_ssh_persists_the_host_alias_outside_the_project(
    tmp_path: Path, fake_bin: Path
) -> None:
    project = make_project(tmp_path / "project")
    before = {path.relative_to(project) for path in project.rglob("*")}
    environment, log = contract_environment(tmp_path, fake_bin)

    saved = invoke(project, environment, "--use", "ssh", "--host", "lab-gpu")
    invoke(project, environment, "benchmark")

    assert "backend=host-ssh, host=lab-gpu" in saved.stdout
    call = engine_calls(log)[0]
    assert_assignment(call, "BACKEND", "host-ssh")
    assert_assignment(call, "SSH_HOST", "lab-gpu")
    assert_remote_target(call, "benchmark")
    assert {path.relative_to(project) for path in project.rglob("*")} == before
    preference = next((tmp_path / "config" / "projects").glob("*.json"))
    assert json.loads(preference.read_text(encoding="utf-8"))["host"] == "lab-gpu"


def test_one_off_ssh_host_does_not_replace_the_saved_host(
    tmp_path: Path, fake_bin: Path
) -> None:
    project = make_project(tmp_path / "project")
    environment, log = contract_environment(tmp_path, fake_bin)
    invoke(project, environment, "--use", "ssh", "--host", "lab-gpu")

    invoke(project, environment, "--host", "oci-free", "build")
    invoke(project, environment, "test")

    first, second = engine_calls(log)
    assert_assignment(first, "SSH_HOST", "oci-free")
    assert_assignment(second, "SSH_HOST", "lab-gpu")


@pytest.mark.parametrize(
    "arguments",
    [
        ("--use", "ssh"),
        ("-b", "ssh", "build"),
    ],
)
def test_ssh_backend_requires_an_explicit_or_saved_host(
    tmp_path: Path, fake_bin: Path, arguments: tuple[str, ...]
) -> None:
    project = make_project(tmp_path / "project")
    environment, log = contract_environment(tmp_path, fake_bin)

    result = invoke(project, environment, *arguments, check=False)

    assert result.returncode == 2
    assert "requires --host HOST" in result.stdout
    assert engine_calls(log) == []


def test_host_option_is_rejected_for_provider_owned_backends(
    tmp_path: Path, fake_bin: Path
) -> None:
    project = make_project(tmp_path / "project")
    environment, log = contract_environment(tmp_path, fake_bin)

    result = invoke(
        project, environment, "-b", "codespaces", "--host", "lab-gpu", "build", check=False
    )

    assert result.returncode == 2
    assert "valid only with the ssh backend" in result.stdout
    assert engine_calls(log) == []


@pytest.mark.parametrize(
    "host", ["researcher@lab.example --bad-option", "-V"]
)
def test_ssh_host_alias_must_be_safe_before_engine_dispatch(
    tmp_path: Path, fake_bin: Path, host: str
) -> None:
    project = make_project(tmp_path / "project")
    environment, log = contract_environment(tmp_path, fake_bin)

    result = invoke(
        project,
        environment,
        "-b",
        "ssh",
        "--host",
        host,
        "build",
        check=False,
    )

    assert result.returncode == 2
    assert "SSH host aliases must begin with" in result.stdout
    assert engine_calls(log) == []


def test_repository_configuration_cannot_choose_a_local_ssh_host(
    tmp_path: Path, fake_bin: Path
) -> None:
    project = make_project(tmp_path / "project")
    (project / ".cloudmake.json").write_text(
        json.dumps({"backend": "ssh", "host": "repo-controlled-host"}),
        encoding="utf-8",
    )
    environment, log = contract_environment(tmp_path, fake_bin)

    result = invoke(project, environment, "build", check=False)

    assert result.returncode == 2
    assert "requires --host HOST" in result.stdout
    assert engine_calls(log) == []


@pytest.mark.parametrize(
    ("alias", "canonical", "extra"),
    [
        ("colab", "colab-notebook", ()),
        ("kaggle", "kaggle-notebook", ()),
        ("codespaces", "codespaces-ssh", ()),
        ("colab-ssh", "colab-ssh", ()),
        ("ssh", "host-ssh", ("--host", "lab-gpu")),
        ("lightning", "lightning-studio-ssh", ()),
    ],
)
def test_backend_aliases_have_unambiguous_canonical_names(
    tmp_path: Path,
    fake_bin: Path,
    alias: str,
    canonical: str,
    extra: tuple[str, ...],
) -> None:
    project = make_project(tmp_path / "project")
    environment, log = contract_environment(tmp_path, fake_bin)

    invoke(project, environment, "-b", alias, *extra, "test")

    assert_assignment(engine_calls(log)[0], "BACKEND", canonical)


def test_one_off_backend_does_not_replace_saved_preference(
    tmp_path: Path, fake_bin: Path
) -> None:
    project = make_project(tmp_path / "project")
    environment, log = contract_environment(tmp_path, fake_bin)
    invoke(project, environment, "--use", "colab")

    invoke(project, environment, "-b", "kaggle", "test")
    invoke(project, environment, "build")

    first, second = engine_calls(log)
    assert_assignment(first, "BACKEND", "kaggle-notebook")
    assert_assignment(second, "BACKEND", "colab-notebook")


def test_global_preference_applies_to_multiple_projects(
    tmp_path: Path, fake_bin: Path
) -> None:
    first_project = make_project(tmp_path / "first")
    second_project = make_project(tmp_path / "second")
    environment, log = contract_environment(tmp_path, fake_bin)

    invoke(first_project, environment, "--use", "kaggle", "--global")
    invoke(first_project, environment, "build")
    invoke(second_project, environment, "test")

    first, second = engine_calls(log)
    assert_assignment(first, "BACKEND", "kaggle-notebook")
    assert_assignment(second, "BACKEND", "kaggle-notebook")


def test_command_line_backend_overrides_environment_and_saved_preference(
    tmp_path: Path, fake_bin: Path
) -> None:
    project = make_project(tmp_path / "project")
    environment, log = contract_environment(tmp_path, fake_bin)
    invoke(project, environment, "--use", "colab")
    environment["CLOUDMAKE_BACKEND"] = "kaggle"

    invoke(project, environment, "-b", "codespaces", "build")

    assert_assignment(engine_calls(log)[0], "BACKEND", "codespaces-ssh")


def test_environment_backend_overrides_saved_preference(
    tmp_path: Path, fake_bin: Path
) -> None:
    project = make_project(tmp_path / "project")
    environment, log = contract_environment(tmp_path, fake_bin)
    invoke(project, environment, "--use", "colab")
    environment["CLOUDMAKE_BACKEND"] = "kaggle"

    invoke(project, environment, "build")

    assert_assignment(engine_calls(log)[0], "BACKEND", "kaggle-notebook")


def test_dash_c_selects_project_without_changing_shell_directory(
    tmp_path: Path, fake_bin: Path
) -> None:
    caller = tmp_path / "caller"
    caller.mkdir()
    project = make_project(tmp_path / "other-project")
    environment, log = contract_environment(tmp_path, fake_bin)

    invoke(caller, environment, "-C", str(project), "-b", "colab", "build")

    assert_assignment(engine_calls(log)[0], "PROJECT_DIR", str(project.resolve()))


def test_unknown_target_and_make_assignments_are_dispatched_losslessly(
    tmp_path: Path, fake_bin: Path
) -> None:
    project = make_project(tmp_path / "project")
    environment, log = contract_environment(tmp_path, fake_bin)

    invoke(project, environment, "-b", "colab", "benchmark", "SIZE=large", "DEBUG=1")

    call = engine_calls(log)[0]
    assert_remote_target(call, "benchmark")
    assert project_arguments(call) == ["SIZE=large", "DEBUG=1"]
    assert "SIZE=large" not in call
    assert "DEBUG=1" not in call
    assert "dispatch" in call


@pytest.mark.parametrize(
    "target", ["start", "sync", "status", "fetch", "open", "shell", "stop", "doctor", "backends", "collect", "package", "help", "exec", "release candidate's [gpu]"]
)
def test_cloud_operation_words_are_unconditionally_project_targets(
    tmp_path: Path, fake_bin: Path, target: str
) -> None:
    project = make_project(tmp_path / "project")
    environment, log = contract_environment(tmp_path, fake_bin)

    invoke(project, environment, "-b", "colab", target)

    call = engine_calls(log)[0]
    assert_remote_target(call, target)
    assert "dispatch" in call


def test_collect_option_runs_any_target_and_fetches_its_output(
    tmp_path: Path, fake_bin: Path
) -> None:
    project = make_project(tmp_path / "project")
    environment, log = contract_environment(tmp_path, fake_bin)

    invoke(
        project,
        environment,
        "-b",
        "colab",
        "--collect",
        "dist/release",
        "benchmark",
        "MODE=release",
    )

    call = engine_calls(log)[0]
    assert "collect" in call
    assert "dispatch" not in call
    assert_remote_target(call, "benchmark")
    assert_collect_directory(call, "dist/release")
    assert project_arguments(call) == ["MODE=release"]
    assert "MODE=release" not in call


def test_collect_requires_a_project_target(tmp_path: Path, fake_bin: Path) -> None:
    project = make_project(tmp_path / "project")
    environment, log = contract_environment(tmp_path, fake_bin)

    result = invoke(project, environment, "--collect", check=False)

    assert result.returncode == 2
    assert "requires a directory and project target" in result.stdout
    assert engine_calls(log) == []


@pytest.mark.parametrize("directory", ["/absolute", "../escape", "dist/../../escape"])
def test_collect_rejects_unsafe_directories_before_invoking_engine(
    tmp_path: Path, fake_bin: Path, directory: str
) -> None:
    project = make_project(tmp_path / "project")
    environment, log = contract_environment(tmp_path, fake_bin)

    result = invoke(
        project, environment, "--collect", directory, "benchmark", check=False
    )

    assert result.returncode == 2
    assert "safe project-relative path" in result.stdout
    assert engine_calls(log) == []


def test_package_option_is_not_a_second_target_namespace(
    tmp_path: Path, fake_bin: Path
) -> None:
    project = make_project(tmp_path / "project")
    environment, log = contract_environment(tmp_path, fake_bin)

    result = invoke(project, environment, "--package", check=False)

    assert result.returncode == 2
    assert "unknown cloudmake option" in result.stdout
    assert engine_calls(log) == []


@pytest.mark.parametrize("command", ["start", "sync", "sync-dry-run", "status", "fetch", "open", "shell", "stop"])
def test_lifecycle_options_are_not_remote_make_targets(
    tmp_path: Path, fake_bin: Path, command: str
) -> None:
    project = make_project(tmp_path / "project")
    environment, log = contract_environment(tmp_path, fake_bin)

    invoke(project, environment, "-b", "colab", f"--{command}")

    call = engine_calls(log)[0]
    assert command in call
    assert not any(argument.startswith("REMOTE_TARGET_B64=") for argument in call)


def test_project_variables_cannot_reconfigure_the_host_engine(
    tmp_path: Path, fake_bin: Path
) -> None:
    project = make_project(tmp_path / "project")
    environment, log = contract_environment(tmp_path, fake_bin)

    invoke(
        project,
        environment,
        "-b",
        "kaggle",
        "-j",
        "8",
        "build",
        "KAGGLE_TIMEOUT=7200",
        "KAGGLE_ACCELERATOR=NvidiaL4",
    )

    call = engine_calls(log)[0]
    assert_assignment(call, "JOBS", "8")
    assert project_arguments(call) == [
        "KAGGLE_TIMEOUT=7200",
        "KAGGLE_ACCELERATOR=NvidiaL4",
    ]
    assert "KAGGLE_TIMEOUT=7200" not in call
    assert "KAGGLE_ACCELERATOR=NvidiaL4" not in call


@pytest.mark.parametrize("option", ["--doctor", "--start", "--sync", "--status", "--fetch", "--open", "--shell", "--stop"])
def test_cloud_operations_reject_trailing_project_arguments(
    tmp_path: Path, fake_bin: Path, option: str
) -> None:
    project = make_project(tmp_path / "project")
    environment, log = contract_environment(tmp_path, fake_bin)

    result = invoke(project, environment, option, "NAME=value", check=False)

    assert result.returncode == 2
    assert "does not accept positional arguments" in result.stdout
    assert engine_calls(log) == []


@pytest.mark.parametrize(
    "arguments",
    [
        ("-b", "codespaces", "--gpu=T4", "build"),
        ("--use", "codespaces", "--gpu=T4"),
        ("-b", "ssh", "--host", "lab-gpu", "--gpu=T4", "build"),
        ("--use", "ssh", "--host", "lab-gpu", "--gpu=T4"),
    ],
)
def test_accelerator_request_is_rejected_when_backend_cannot_select_hardware(
    tmp_path: Path, fake_bin: Path, arguments: tuple[str, ...]
) -> None:
    project = make_project(tmp_path / "project")
    environment, log = contract_environment(tmp_path, fake_bin)

    result = invoke(project, environment, *arguments, check=False)

    assert result.returncode == 2
    assert "does not support accelerator requests" in result.stdout
    assert engine_calls(log) == []


def test_lightning_gpu_request_selects_studio_machine(
    tmp_path: Path, fake_bin: Path
) -> None:
    project = make_project(tmp_path / "project")
    environment, log = contract_environment(tmp_path, fake_bin)

    invoke(project, environment, "-b", "lightning", "--gpu=T4", "build")

    call = engine_calls(log)[0]
    assert_assignment(call, "BACKEND", "lightning-studio-ssh")
    assert_assignment(call, "LIGHTNING_MACHINE", "T4")


def test_unknown_backend_fails_without_invoking_engine(
    tmp_path: Path, fake_bin: Path
) -> None:
    project = make_project(tmp_path / "project")
    environment, log = contract_environment(tmp_path, fake_bin)

    result = invoke(project, environment, "-b", "unknown", "build", check=False)

    assert result.returncode != 0
    assert "unknown backend" in result.stdout.lower()
    assert engine_calls(log) == []


def test_compute_target_requires_project_makefile(
    tmp_path: Path, fake_bin: Path
) -> None:
    project = tmp_path / "empty-project"
    project.mkdir()
    environment, log = contract_environment(tmp_path, fake_bin)

    result = invoke(project, environment, "-b", "colab", "build", check=False)

    assert result.returncode != 0
    assert "makefile" in result.stdout.lower()
    assert engine_calls(log) == []


def test_credentials_are_not_written_to_project_or_cloudmake_preferences(
    tmp_path: Path, fake_bin: Path
) -> None:
    project = make_project(tmp_path / "project")
    environment, _ = contract_environment(tmp_path, fake_bin)
    sentinel = "must-not-be-persisted-secret"
    environment["GITHUB_TOKEN"] = sentinel
    environment["KAGGLE_API_TOKEN"] = sentinel

    invoke(project, environment, "--use", "codespaces")

    persisted = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for root_name in ("config", "state", "cache")
        for path in (tmp_path / root_name).rglob("*")
        if path.is_file()
    )
    assert sentinel not in persisted
    assert all(
        sentinel not in path.read_text(encoding="utf-8")
        for path in project.rglob("*")
        if path.is_file()
    )


def test_execution_provenance_hashes_assignment_values_and_tracks_result(
    tmp_path: Path, fake_bin: Path
) -> None:
    project = make_project(tmp_path / "project")
    environment, log = contract_environment(tmp_path, fake_bin)
    secret = "do-not-store-this-value"

    result = invoke(project, environment, "benchmark", f"TOKEN={secret}")

    latest_records = list((tmp_path / "state" / "projects").glob("*/runs/latest.json"))
    assert len(latest_records) == 1
    latest = latest_records[0]
    record = json.loads(latest.read_text(encoding="utf-8"))
    assert record["status"] == "succeeded"
    assert record["target"] == "benchmark"
    assert record["exit_code"] == 0
    assert record["assignments"][0]["name"] == "TOKEN"
    assert len(record["assignments"][0]["value_sha256"]) == 64
    assert secret not in latest.read_text(encoding="utf-8")
    assert latest.stat().st_mode & 0o077 == 0
    assert f"run={record['run_id']}" in result.stdout
    assert any(
        argument == f"CLOUDMAKE_RUN_ID={record['run_id']}"
        for argument in engine_calls(log)[0]
    )


def test_failed_execution_is_retained_in_provenance(
    tmp_path: Path, fake_bin: Path
) -> None:
    project = make_project(tmp_path / "project")
    environment, _ = contract_environment(tmp_path, fake_bin)
    environment["CLOUDMAKE_TEST_ENGINE_EXIT"] = "7"

    result = invoke(project, environment, "build", check=False)

    latest = next((tmp_path / "state" / "projects").glob("*/runs/latest.json"))
    record = json.loads(latest.read_text(encoding="utf-8"))
    assert result.returncode == 7
    assert record["status"] == "failed"
    assert record["exit_code"] == 7


def test_history_lists_recent_execution_without_invoking_engine_again(
    tmp_path: Path, fake_bin: Path
) -> None:
    project = make_project(tmp_path / "project")
    environment, log = contract_environment(tmp_path, fake_bin)
    invoke(project, environment, "benchmark")
    before = engine_calls(log)

    history = invoke(project, environment, "--history")

    assert "succeeded" in history.stdout
    assert "benchmark" in history.stdout
    assert "Provenance directory" in history.stdout
    assert engine_calls(log) == before
