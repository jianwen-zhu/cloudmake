from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from conftest import PROJECT_ROOT, run_command


PREPARE = PROJECT_ROOT / "tests" / "compatibility" / "devcontainers" / "prepare.sh"
CONFIG_TOOL = PROJECT_ROOT / "core" / "devcontainer_config.py"
LAUNCHER = PROJECT_ROOT / "cmd" / "cloudmake"

EXPECTED = {
    "cpp": {"image-build"},
    "go": {"image-digest", "port-attributes"},
    "java": {"features", "image-digest"},
    "node": {"image-digest", "lifecycle-create", "port-attributes"},
    "python": {"image-digest", "lifecycle-create", "port-attributes"},
    "rust": {"image-digest"},
    "ubuntu": {"image-digest"},
}


def test_real_devcontainer_prepare_script_is_valid_posix_shell() -> None:
    run_command(["sh", "-n", PREPARE], cwd=PROJECT_ROOT)


def test_real_devcontainer_corpus_is_revision_and_digest_pinned() -> None:
    source = PREPARE.read_text(encoding="utf-8")

    assert source.count("https://github.com/") == 7
    assert source.count("@sha256:") == 6
    assert "latest" not in source
    assert "${templateOption:imageVariant}" in source


def test_real_devcontainer_corpus_does_not_embed_credentials() -> None:
    source = PREPARE.read_text(encoding="utf-8")

    assert "Authorization:" not in source
    assert "Bearer " not in source
    assert "github_pat_" not in source
    assert "ghp_" not in source


@pytest.mark.real_github
@pytest.mark.skipif(
    os.environ.get("CLOUDMAKE_TEST_REAL_DEVCONTAINERS") != "1",
    reason=(
        "set CLOUDMAKE_TEST_REAL_DEVCONTAINERS=1 to clone and execute the "
        "pinned public Dev Container corpus"
    ),
)
def test_pinned_public_devcontainer_compatibility_corpus(tmp_path: Path) -> None:
    prepared = tmp_path / "devcontainers"
    result = run_command([PREPARE, prepared], cwd=PROJECT_ROOT, timeout=240)
    projects = {Path(value).name: Path(value) for value in result.stdout.splitlines()}

    assert set(projects) == set(EXPECTED)
    for name, expected in EXPECTED.items():
        parsed = run_command(
            ["python3", CONFIG_TOOL, "--project", projects[name]],
            cwd=PROJECT_ROOT,
            check=False,
        )
        assert parsed.returncode == 0, parsed.stdout
        profile = json.loads(parsed.stdout)
        assert expected <= set(profile["required_capabilities"])

    expected_output = {
        "cpp": "cpp-devcontainer=ok",
        "rust": "Hello, VS Code Remote - Containers!",
        "ubuntu": "workspace=ok",
    }
    for name, marker in expected_output.items():
        state = tmp_path / f"state-{name}"
        container_id = ""
        try:
            executed = run_command(
                [LAUNCHER, "-b", "local", "--devcontainer", "verify"],
                cwd=projects[name],
                env={
                    "CLOUDMAKE_CONFIG_HOME": str(state / "config"),
                    "CLOUDMAKE_STATE_HOME": str(state / "state"),
                    "CLOUDMAKE_CACHE_HOME": str(state / "cache"),
                },
                timeout=900,
            )
            expected_runner = (
                "runner=devcontainer-native" if name == "cpp" else "runtime=docker"
            )
            assert expected_runner in executed.stdout
            assert marker in executed.stdout
            if name == "cpp":
                latest = next((state / "state" / "projects").glob("*/runs/latest.json"))
                provenance = json.loads(latest.read_text(encoding="utf-8"))
                assert provenance["runner"]["image_id"].startswith("sha256:")
                assert provenance["runner"]["platform"].startswith("linux/")
                assert provenance["runner"]["target_submission"] == "confirmed"
                container_id = provenance["runner"]["container_id"]
        finally:
            if name == "cpp" and not container_id:
                records = list((state / "state" / "projects").glob("*/runs/latest.json"))
                if records:
                    provenance = json.loads(records[0].read_text(encoding="utf-8"))
                    container_id = provenance.get("runner", {}).get("container_id", "")
            if container_id:
                run_command(
                    ["docker", "rm", "-f", container_id],
                    cwd=PROJECT_ROOT,
                    check=False,
                )
