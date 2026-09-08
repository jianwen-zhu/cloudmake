from __future__ import annotations

from pathlib import Path
import subprocess

from conftest import PROJECT_ROOT


HARNESS = PROJECT_ROOT / "tests" / "acceptance" / "orfs-checkpoint" / "run.sh"
PROJECT = PROJECT_ROOT / "tests" / "acceptance" / "orfs-checkpoint" / "project"


def test_orfs_acceptance_harness_is_valid_posix_shell() -> None:
    subprocess.run(["sh", "-n", HARNESS], check=True)


def test_orfs_acceptance_harness_preserves_ambiguous_session() -> None:
    source = HARNESS.read_text(encoding="utf-8")

    assert "--persist" in source
    assert "snapshot-published=" in source
    assert "snapshot-restored=" in source
    assert "left intact for inspection" in source
    assert "trap" not in source


def test_orfs_acceptance_project_is_statically_valid_and_pinned() -> None:
    launcher = PROJECT / "orfs-acceptance.sh"
    subprocess.run(["sh", "-n", launcher], check=True)
    source = launcher.read_text(encoding="utf-8")
    makefile = (PROJECT / "Makefile").read_text(encoding="utf-8")

    assert "ORFS_COMMIT=68cc9bc974502b4786a68e9f51a092e0fcb56e82" in source
    assert "ORFS_IMAGE=openroad/orfs:26Q3-488-g68cc9bc97" in source
    assert "APPTAINER_VERSION=1.5.3" in source
    assert "APPTAINER_TMPDIR=$PWD/$state/apptainer-tmp" in source
    assert "result=$orfs/results/nangate45/gcd/base" in source
    assert "2_floorplan.odb" in source
    assert "3_place.odb" in source
    assert "stage2_reused_floorplan=yes" in source
    assert "CLOUDMAKE" not in makefile
    assert "orfs-floorplan:" in makefile
    assert "orfs-place:" in makefile


def test_orfs_acceptance_project_does_not_embed_credentials() -> None:
    source = (PROJECT / "orfs-acceptance.sh").read_text(encoding="utf-8")

    for forbidden in (
        "GOOGLE_APPLICATION_CREDENTIALS",
        "GITHUB_TOKEN",
        "RESTIC_PASSWORD",
        "docker login",
        "apptainer remote login",
    ):
        assert forbidden not in source
