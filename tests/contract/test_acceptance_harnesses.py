from __future__ import annotations

from pathlib import Path
import subprocess

from conftest import PROJECT_ROOT


HARNESS = PROJECT_ROOT / "tests" / "acceptance" / "orfs-checkpoint" / "run.sh"
PROJECT = PROJECT_ROOT / "tests" / "acceptance" / "orfs-checkpoint" / "project"
OCI_HARNESS = PROJECT_ROOT / "tests" / "acceptance" / "orfs-oci" / "run.sh"
OCI_PROJECT = PROJECT_ROOT / "tests" / "acceptance" / "orfs-oci" / "project"
CODESPACES_COURSES = (
    PROJECT_ROOT / "tests" / "acceptance" / "codespaces-courses" / "run.sh"
)
CODESPACES_NETWORK = (
    PROJECT_ROOT / "tests" / "acceptance" / "codespaces-network" / "run.sh"
)
CODESPACES_NETWORK_PROJECT = (
    PROJECT_ROOT / "tests" / "acceptance" / "codespaces-network" / "project"
)


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


def test_orfs_oci_acceptance_is_digest_pinned_and_composes_persistence() -> None:
    subprocess.run(["sh", "-n", OCI_HARNESS], check=True)
    launcher = OCI_PROJECT / "orfs-oci.sh"
    subprocess.run(["sh", "-n", launcher], check=True)
    harness = OCI_HARNESS.read_text(encoding="utf-8")
    source = launcher.read_text(encoding="utf-8")
    makefile = (OCI_PROJECT / "Makefile").read_text(encoding="utf-8")

    digest = "sha256:cdb377cec7796c5cb01d482ca035811bfe559ca55dcca7f5e5f46fa811c63142"
    assert f"docker.io/openroad/orfs@{digest}" in harness
    assert f"docker.io/openroad/orfs@{digest}" in source
    assert "--image" in harness
    assert "--gpu=T4" in harness
    assert "--device nvidia.com/gpu=all" in harness
    assert "--persist" in harness
    assert "snapshot-restored=" in harness
    assert "stage2_reused_floorplan=yes" in source
    assert "APPTAINER" not in source
    assert "docker run" not in source
    assert "nvidia-smi" in source
    assert "CLOUDMAKE" not in makefile


def test_orfs_oci_acceptance_does_not_embed_credentials() -> None:
    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (OCI_HARNESS, OCI_PROJECT / "orfs-oci.sh")
    )
    for forbidden in (
        "GOOGLE_APPLICATION_CREDENTIALS",
        "GITHUB_TOKEN",
        "RESTIC_PASSWORD",
        "docker login",
        "Authorization:",
    ):
        assert forbidden not in combined


def test_codespaces_course_gate_is_bounded_and_reuses_one_workstation() -> None:
    subprocess.run(["sh", "-n", CODESPACES_COURSES], check=True)
    source = CODESPACES_COURSES.read_text(encoding="utf-8")

    assert "leaderboard-pair-ready" in source
    assert "lab-axpy-01-cpu" in source
    assert "lab-gemm-01-cpu" in source
    assert "llmc-test" in source
    assert "ttl-build" not in source
    assert "--gpu" not in source
    assert source.count("course_image") >= 4
    assert "--stop" in source


def test_codespaces_network_gate_is_private_and_cleans_up() -> None:
    subprocess.run(["sh", "-n", CODESPACES_NETWORK], check=True)
    source = CODESPACES_NETWORK.read_text(encoding="utf-8")
    makefile = (CODESPACES_NETWORK_PROJECT / "Makefile").read_text(
        encoding="utf-8"
    )

    assert "codespace ports forward" in source
    assert "visibility=authenticated-private" in source
    assert "ports visibility" not in source
    assert "public" not in source
    assert "stop-server" in source
    assert "--stop" in source
    assert "python3 -m http.server" in makefile
    assert "CLOUDMAKE" not in makefile


def test_codespaces_live_gates_do_not_embed_credentials() -> None:
    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (CODESPACES_COURSES, CODESPACES_NETWORK)
    )
    for forbidden in (
        "GITHUB_TOKEN",
        "GH_TOKEN",
        "Authorization:",
        "gh auth token",
        "gh auth login",
    ):
        assert forbidden not in combined
