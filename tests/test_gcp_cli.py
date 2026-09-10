from __future__ import annotations

import json
import os
from pathlib import Path

from conftest import run_command, write_executable


def isolated_environment(tmp_path: Path) -> dict[str, str]:
    return {
        "CLOUDMAKE_CONFIG_HOME": os.fspath(tmp_path / "config"),
        "CLOUDMAKE_STATE_HOME": os.fspath(tmp_path / "state"),
        "CLOUDMAKE_CACHE_HOME": os.fspath(tmp_path / "cache"),
    }


def test_use_gcp_persists_only_resource_coordinates(
    prototype: Path, tmp_path: Path
) -> None:
    environment = {
        **isolated_environment(tmp_path),
        "GCP_PROJECT": "example-project",
        "GCP_ZONE": "us-central1-a",
        "GCP_INSTANCE": "workstation",
        "GCP_TUNNEL_THROUGH_IAP": "yes",
        "GOOGLE_APPLICATION_CREDENTIALS": "/secret/credentials.json",
        "CLOUDSDK_AUTH_ACCESS_TOKEN": "secret-token",
    }

    result = run_command(
        [prototype / "bin" / "cloudmake", "--use", "gcp"],
        cwd=prototype,
        env=environment,
    )

    assert "subsequent targets reuse this selection" in result.stdout
    project_files = list((tmp_path / "config" / "projects").glob("*.json"))
    assert len(project_files) == 1
    saved = json.loads(project_files[0].read_text(encoding="utf-8"))
    assert saved["backend"] == "gcp-compute-ssh"
    assert saved["gcp"] == {
        "project": "example-project",
        "zone": "us-central1-a",
        "instance": "workstation",
        "tunnel_through_iap": "yes",
    }
    serialized = json.dumps(saved)
    assert "secret-token" not in serialized
    assert "credentials.json" not in serialized


def test_gcp_help_does_not_require_a_configured_resource(
    prototype: Path, tmp_path: Path
) -> None:
    result = run_command(
        [prototype / "bin" / "cloudmake", "-b", "gcp", "--help"],
        cwd=prototype,
        env=isolated_environment(tmp_path),
    )
    assert "Backend: gcp-compute-ssh" in result.stdout


def test_gcp_execution_rejects_incomplete_selection_before_provider(
    prototype: Path, tmp_path: Path
) -> None:
    result = run_command(
        [prototype / "bin" / "cloudmake", "-b", "gcp", "smoke"],
        cwd=prototype,
        env={**isolated_environment(tmp_path), "GCP_PROJECT": "example-project"},
        check=False,
    )
    assert result.returncode == 2
    assert "incomplete GCP resource selection" in result.stdout


def fake_gcloud(path: Path) -> Path:
    return write_executable(
        path,
        r"""#!/usr/bin/env python3
import json
import os
from pathlib import Path
import subprocess
import sys

arguments = sys.argv[1:]
state_file = Path(os.environ["FAKE_GCP_STATE"])
remote_home = Path(os.environ["FAKE_GCP_HOME"])
state = state_file.read_text(encoding="utf-8").strip() if state_file.exists() else "RUNNING"
if arguments[:1] == ["version"]:
    print("Google Cloud SDK fake")
elif arguments[:2] == ["auth", "list"]:
    if not os.environ.get("FAKE_AUTH_DENIED"):
        print("developer@example.invalid")
elif arguments[:3] == ["compute", "instances", "describe"]:
    print(json.dumps({
        "name": "workstation",
        "status": state,
        "machineType": "zones/us-central1-a/machineTypes/e2-micro",
    }))
elif arguments[:3] == ["compute", "instances", "start"]:
    state_file.write_text("RUNNING\n", encoding="utf-8")
elif arguments[:3] == ["compute", "instances", "resume"]:
    state_file.write_text("RUNNING\n", encoding="utf-8")
elif arguments[:3] == ["compute", "instances", "stop"]:
    state_file.write_text("TERMINATED\n", encoding="utf-8")
elif arguments[:2] == ["compute", "ssh"]:
    if "--command" not in arguments:
        raise SystemExit(0)
    command = arguments[arguments.index("--command") + 1]
    remote_home.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ, HOME=os.fspath(remote_home))
    raise SystemExit(subprocess.run(command, shell=True, cwd=remote_home, env=environment).returncode)
else:
    print("unexpected fake gcloud arguments: " + repr(arguments), file=sys.stderr)
    raise SystemExit(2)
""",
    )


def test_fake_provider_full_target_stop_restart_and_native_persistence(
    prototype: Path, tmp_path: Path
) -> None:
    project = tmp_path / "consumer"
    project.mkdir()
    (project / "Makefile").write_text(
        "smoke:\n"
        "\t@mkdir -p build\n"
        "\t@n=$$(cat build/count 2>/dev/null || echo 0); "
        "n=$$((n + 1)); printf '%s\\n' $$n > build/count; "
        "printf 'remote-count=%s\\n' $$n\n"
        "fail-once:\n"
        "\t@mkdir -p build\n"
        "\t@n=$$(cat build/fail-count 2>/dev/null || echo 0); "
        "n=$$((n + 1)); printf '%s\\n' $$n > build/fail-count; exit 7\n",
        encoding="utf-8",
    )
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_gcloud(fake_bin / "gcloud")
    provider_state = tmp_path / "provider-state"
    provider_state.write_text("TERMINATED\n", encoding="utf-8")
    environment = {
        **isolated_environment(tmp_path),
        "PATH": os.pathsep.join((os.fspath(fake_bin), os.environ["PATH"])),
        "GCP_PROJECT": "example-project",
        "GCP_ZONE": "us-central1-a",
        "GCP_INSTANCE": "workstation",
        "FAKE_GCP_STATE": os.fspath(provider_state),
        "FAKE_GCP_HOME": os.fspath(tmp_path / "remote"),
    }

    first = run_command(
        [prototype / "bin" / "cloudmake", "-C", project, "-b", "gcp", "smoke"],
        cwd=prototype,
        env=environment,
        timeout=60,
    )
    second = run_command(
        [prototype / "bin" / "cloudmake", "-C", project, "-b", "gcp", "smoke"],
        cwd=prototype,
        env=environment,
        timeout=60,
    )
    profile = run_command(
        [prototype / "bin" / "cloudmake", "-C", project, "-b", "gcp", "--environment"],
        cwd=prototype,
        env=environment,
        timeout=60,
    )
    stopped = run_command(
        [prototype / "bin" / "cloudmake", "-C", project, "-b", "gcp", "--stop"],
        cwd=prototype,
        env=environment,
        timeout=60,
    )
    status = run_command(
        [prototype / "bin" / "cloudmake", "-C", project, "-b", "gcp", "--status"],
        cwd=prototype,
        env=environment,
        timeout=60,
    )
    third = run_command(
        [prototype / "bin" / "cloudmake", "-C", project, "-b", "gcp", "smoke"],
        cwd=prototype,
        env=environment,
        timeout=60,
    )
    failed = run_command(
        [prototype / "bin" / "cloudmake", "-C", project, "-b", "gcp", "fail-once"],
        cwd=prototype,
        env=environment,
        check=False,
        timeout=60,
    )

    assert "resource=started" in first.stdout
    assert "remote-count=1" in first.stdout
    assert "resource=reused" in second.stdout
    assert "remote-count=2" in second.stdout
    assert "environment evidence=observed" in profile.stdout
    assert "disk=retained" in stopped.stdout
    assert "status=stopped" in status.stdout
    assert provider_state.read_text(encoding="utf-8") == "RUNNING\n"
    assert "resource=started" in third.stdout
    assert "remote-count=3" in third.stdout
    assert failed.returncode != 0
    fail_counts = list(
        (tmp_path / "remote" / ".cloudmake").glob("*/src/build/fail-count")
    )
    assert len(fail_counts) == 1
    assert fail_counts[0].read_text(encoding="utf-8") == "1\n"
    records = [
        path
        for path in (tmp_path / "state").glob("projects/*/runs/*.json")
        if path.name != "latest.json"
    ]
    payloads = [json.loads(path.read_text(encoding="utf-8")) for path in records]
    assert sorted(payload["status"] for payload in payloads) == [
        "failed",
        "succeeded",
        "succeeded",
        "succeeded",
    ]
    assert {payload["backend"] for payload in payloads} == {"gcp-compute-ssh"}
    assert {payload["compute_resource"]["machine_type"] for payload in payloads} == {
        "e2-micro"
    }
    assert all("credential" not in json.dumps(payload).lower() for payload in payloads)


def test_doctor_rejects_absent_gcloud_auth_without_starting_compute(
    prototype: Path, tmp_path: Path
) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_gcloud(fake_bin / "gcloud")
    provider_state = tmp_path / "provider-state"
    provider_state.write_text("TERMINATED\n", encoding="utf-8")
    environment = {
        **isolated_environment(tmp_path),
        "PATH": os.pathsep.join((os.fspath(fake_bin), os.environ["PATH"])),
        "GCP_PROJECT": "example-project",
        "GCP_ZONE": "us-central1-a",
        "GCP_INSTANCE": "workstation",
        "FAKE_GCP_STATE": os.fspath(provider_state),
        "FAKE_GCP_HOME": os.fspath(tmp_path / "remote"),
        "FAKE_AUTH_DENIED": "1",
    }

    result = run_command(
        [prototype / "bin" / "cloudmake", "-C", prototype, "-b", "gcp", "--doctor"],
        cwd=prototype,
        env=environment,
        check=False,
    )

    assert result.returncode == 2
    assert "authentication or access probe failed" in result.stdout
    assert provider_state.read_text(encoding="utf-8") == "TERMINATED\n"
