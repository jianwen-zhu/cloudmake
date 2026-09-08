# ORFS checkpoint acceptance gate

This is the final live acceptance gate for Cloudmake 2.0 persistence. It is not
part of the offline regression suite and it does not define new project target
names.

The repository includes a pinned, small ORFS project at `project/`. Its
Makefile provides:

1. a first target that completes and validates an ORFS stage;
2. a second target that depends on that stage, verifies the restored stage
   output before continuing, and completes a later stage; and
3. a project-relative directory containing the evidence to collect.

The project owns ORFS acquisition, the pinned ORFS/tool versions, the
application launcher, design configuration, stage-validity checks, and output
meaning. For the 2.0 gate that launcher is an ordinary project recipe suitable
for the selected Colab VM; Cloudmake does not recognize or endorse its bundle
format. The later 2.1 gate will instead use Cloudmake's managed OCI/CDI runner.

Use a dedicated session and invoke the lifecycle harness:

```sh
export COLAB_SESSION=cloudmake-orfs-acceptance
export CLOUDMAKE_TEST_LIVE_ORFS_CHECKPOINT=1
tests/acceptance/orfs-checkpoint/run.sh \
  tests/acceptance/orfs-checkpoint/project \
  orfs-floorplan orfs-place evidence
```

The target names belong only to this acceptance project; they are not
Cloudmake commands or project-contract requirements. The harness enables
persistence, runs stage 1, requires a
published checkpoint, destroys the VM, runs stage 2 in a replacement VM,
requires restore and publication evidence, collects the requested directory,
and then stops the second VM.

If a target or checkpoint operation fails, the harness exits immediately and
leaves the current session intact for inspection. It never stops a VM whose
target completion is ambiguous. Drive authorization may be required in the
foreground for each newly allocated VM; this known Colab limitation is part of
the observed acceptance experience.

The gate passes only if the collected project evidence independently proves
that stage 2 consumed the restored stage-1 output without rebuilding it. Log
strings alone prove Cloudmake's restore/publish lifecycle, not ORFS database
validity.
