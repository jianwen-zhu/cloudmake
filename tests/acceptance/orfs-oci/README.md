# ORFS OCI/CDI acceptance gate

This opt-in live gate is the final application verdict for Cloudmake 2.1. It
uses a digest-pinned official ORFS OCI image directly through Cloudmake's
managed OCI runner; it does not install Apptainer or convert the image to SIF.

The project-owned Makefile first checks the image tool suite, completes ORFS
floorplan for the Nangate45 GCD design, and records a database checksum. The
harness then enables the Cloudmake 2.0 persistent workspace, checkpoints the
completed stage, destroys the Colab VM, restores into a replacement VM, pulls
the same immutable tool image, and completes placement without rebuilding the
floorplan. This validates runner and persistence composition rather than
conflating image layers with mutable workspace state.

Run only with a dedicated session and foreground Drive authorization available:

```sh
export COLAB_SESSION=cloudmake-orfs-oci-acceptance
export CLOUDMAKE_TEST_LIVE_ORFS_OCI=1
tests/acceptance/orfs-oci/run.sh tests/acceptance/orfs-oci/project evidence
```

The harness stops a VM only after unambiguous success. Any failure leaves the
current session intact for inspection. The pinned image is Linux/amd64 and may
require several gigabytes of VM disk while materialized; registry transfer and
fresh-VM materialization time are part of this acceptance experience.
