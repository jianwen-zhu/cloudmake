from __future__ import annotations

import json
import os
from pathlib import Path
import sys

from conftest import PROJECT_ROOT, run_command, write_executable


TOOL = PROJECT_ROOT / "tools" / "devcontainer_native.py"


def fake_tools(directory: Path) -> Path:
    directory.mkdir(exist_ok=True)
    write_executable(
        directory / "devcontainer",
        """#!/usr/bin/env python3
import json, os, sys
with open(os.environ['FAKE_LOG'], 'a', encoding='utf-8') as stream:
    stream.write(json.dumps(sys.argv[1:]) + '\\n')
if sys.argv[1] == 'up':
    print(json.dumps({'outcome': 'success', 'containerId': 'container-123'}))
    raise SystemExit(int(os.environ.get('FAKE_UP_EXIT', '0')))
if 'command -v make >/dev/null' in sys.argv:
    raise SystemExit(0)
if os.environ.get('FAKE_OMIT_MARKER') != '1':
    for value in sys.argv:
        if value.startswith('cloudmake-target-submitted-'):
            print(value)
print('project make output')
raise SystemExit(int(os.environ.get('FAKE_TARGET_EXIT', '0')))
""",
    )
    write_executable(
        directory / "docker",
        """#!/usr/bin/env python3
import json, os, sys
if sys.argv[1] == 'inspect' and any('cloudmake.project' in value for value in sys.argv):
    if os.environ.get('FAKE_CONTAINER_ABSENT') != '1':
        print(os.environ.get('FAKE_OWNER', 'project-key'))
    else:
        raise SystemExit(1)
elif sys.argv[1] == 'inspect':
    print('sha256:image-id')
elif sys.argv[1:3] == ['image', 'inspect']:
    if '.Os' in sys.argv[-2]:
        print('linux/amd64')
    else:
        print(json.dumps(['registry.example/tools@sha256:' + 'a' * 64]))
elif sys.argv[1] == 'ps':
    if os.environ.get('FAKE_CONTAINER_PRESENT') == '1':
        print('container-123')
""",
    )
    return directory


def invoke(
    tmp_path: Path, *, fingerprint: str, target_exit: int = 0,
    up_exit: int = 0, omit_marker: bool = False, fake_owner: str = "project-key",
    container_absent: bool = False, container_present: bool = False,
):
    project = tmp_path / "project"
    project.mkdir(exist_ok=True)
    config = project / ".devcontainer" / "devcontainer.json"
    config.parent.mkdir(exist_ok=True)
    config.write_text(json.dumps({"image": "ubuntu:24.04"}), encoding="utf-8")
    log = tmp_path / "commands.jsonl"
    state = tmp_path / "state.json"
    result = tmp_path / f"result-{fingerprint}.json"
    tools = fake_tools(tmp_path / "bin")
    environment = {
        "PATH": os.pathsep.join((str(tools), os.environ["PATH"])),
        "FAKE_LOG": str(log),
        "FAKE_TARGET_EXIT": str(target_exit),
        "FAKE_UP_EXIT": str(up_exit),
        "FAKE_OMIT_MARKER": "1" if omit_marker else "0",
        "FAKE_OWNER": fake_owner,
        "FAKE_CONTAINER_ABSENT": "1" if container_absent else "0",
        "FAKE_CONTAINER_PRESENT": "1" if container_present else "0",
    }
    completed = run_command(
        [
            sys.executable, TOOL, "--project", project,
            "--config", ".devcontainer/devcontainer.json",
            "--project-key", "project-key", "--fingerprint", fingerprint,
            "--target", "verify", "--assignment", "MODE=quick",
            "--state", state, "--result", result,
        ],
        cwd=project,
        env=environment,
        check=False,
    )
    commands = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    return completed, json.loads(result.read_text(encoding="utf-8")), commands


def test_native_engine_prepares_once_and_submits_target_once(tmp_path: Path) -> None:
    first, receipt, commands = invoke(tmp_path, fingerprint="one")

    assert first.returncode == 0
    assert receipt["status"] == "succeeded"
    assert receipt["preparation"] == "started"
    assert receipt["resolved_digest"].endswith("a" * 64)
    assert receipt["platform"] == "linux/amd64"
    assert [command[0] for command in commands] == ["up", "exec", "exec"]
    assert "cloudmake.project=project-key" in commands[0]
    assert "cloudmake.config=one" in commands[0]
    assert commands[-1][-2:] == ["verify", "MODE=quick"]

    second, receipt, commands = invoke(tmp_path, fingerprint="one")
    assert second.returncode == 0
    assert receipt["preparation"] == "reused"
    assert "--remove-existing-container" not in commands[-3]


def test_configuration_change_rebuilds_managed_workstation(tmp_path: Path) -> None:
    invoke(tmp_path, fingerprint="one")
    _, receipt, commands = invoke(tmp_path, fingerprint="two")

    assert receipt["preparation"] == "rebuilt"
    last_up = [command for command in commands if command[0] == "up"][-1]
    assert "cloudmake.config=two" in last_up
    assert "--remove-existing-container" not in last_up


def test_target_failure_is_confirmed_and_not_replayed(tmp_path: Path) -> None:
    completed, receipt, commands = invoke(
        tmp_path, fingerprint="failure", target_exit=7
    )

    assert completed.returncode == 7
    assert receipt["status"] == "target-failed"
    assert receipt["target_submission"] == "confirmed"
    assert receipt["retry_safe"] is False
    target_commands = [command for command in commands if "verify" in command]
    assert len(target_commands) == 1


def test_preparation_failure_never_submits_target(tmp_path: Path) -> None:
    completed, receipt, commands = invoke(
        tmp_path, fingerprint="preparation-failure", up_exit=9
    )

    assert completed.returncode == 9
    assert receipt["status"] == "preparation-failed"
    assert receipt["target_submission"] == "not_submitted"
    assert receipt["retry_safe"] is True
    assert [command[0] for command in commands] == ["up"]


def test_exec_failure_without_submission_evidence_remains_ambiguous(
    tmp_path: Path,
) -> None:
    completed, receipt, commands = invoke(
        tmp_path, fingerprint="ambiguous", target_exit=9, omit_marker=True
    )

    assert completed.returncode == 9
    assert receipt["status"] == "execution-ambiguous"
    assert receipt["target_submission"] == "ambiguous"
    assert receipt["retry_safe"] is False
    assert len([command for command in commands if "verify" in command]) == 1


def test_changed_configuration_never_removes_unowned_container(tmp_path: Path) -> None:
    invoke(tmp_path, fingerprint="one")
    completed, receipt, commands = invoke(
        tmp_path, fingerprint="two", fake_owner="another-project"
    )

    assert completed.returncode == 1
    assert receipt["status"] == "preparation-failed"
    assert receipt["target_submission"] == "not_submitted"
    assert [command[0] for command in commands] == ["up", "exec", "exec"]


def test_changed_configuration_recovers_after_managed_container_is_already_absent(
    tmp_path: Path,
) -> None:
    invoke(tmp_path, fingerprint="one")

    completed, receipt, commands = invoke(
        tmp_path, fingerprint="two", container_absent=True
    )

    assert completed.returncode == 0
    assert receipt["status"] == "succeeded"
    assert receipt["preparation"] == "rebuilt"
    assert [command[0] for command in commands] == [
        "up", "exec", "exec", "up", "exec", "exec"
    ]


def test_interrupted_changed_configuration_recovers_without_target_replay(
    tmp_path: Path,
) -> None:
    invoke(tmp_path, fingerprint="one")

    failed, failed_receipt, commands = invoke(
        tmp_path, fingerprint="two", up_exit=9
    )
    transition = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))

    assert failed.returncode == 9
    assert failed_receipt["target_submission"] == "not_submitted"
    assert transition == {
        "engine_contract": 2,
        "fingerprint": "two",
        "schema": 1,
        "status": "preparing",
    }
    assert [command[0] for command in commands] == ["up", "exec", "exec", "up"]

    recovered, receipt, commands = invoke(tmp_path, fingerprint="two")

    assert recovered.returncode == 0
    assert receipt["preparation"] == "reconstructed"
    assert len([command for command in commands if "verify" in command]) == 2
