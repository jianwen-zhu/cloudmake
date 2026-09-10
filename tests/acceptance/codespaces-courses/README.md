# Codespaces course-consumer acceptance

This opt-in live gate qualifies the Codespaces CPU remote-workstation backend
against the two established course consumers already exercised on local and
Colab backends. It accepts prepared project directories so no course or staff
material is copied into the Cloudmake repository.

The gate runs:

1. ECE326's clean public Lab 1 setup, public tests, and real Bottle benchmark;
2. ECE326's paired Lab 4 tests and bounded leaderboard calibration; and
3. ECE467's project checks, permanent CPU AXPY and GEMM references, and fast
   llm.c reference tests.

It deliberately omits ECE467 bootstrap, CUDA/device/TileLang exercises, model
downloads, and long benchmarks. Codespaces is qualified here as a CPU backend.
The default digest-pinned official Python workstation image supplies Python,
pip, and the conventional compiler toolchain assumed by the two projects; the
Cloudmake adapter adds only its transport tools. ECE326 setup still requires
outbound Internet access for pinned Python packages and model assets, so the
gate also validates actual workload egress. Override `CODESPACES_COURSE_IMAGE`
only with another digest-pinned image satisfying the same project tool surface.

Run it with an existing temporary Codespace created from the neutral Cloudmake
anchor:

```sh
export CODESPACE=cloudmake-course-gate-name
export CLOUDMAKE_TEST_LIVE_CODESPACES_COURSES=1
tests/acceptance/codespaces-courses/run.sh \
  /path/to/ece326-lab1 \
  /path/to/ece326-lab4-pair \
  /path/to/ece467-labs \
  /tmp/cloudmake-codespaces-course-evidence
```

The harness uses one provider-persistent Codespace and one provider-native OCI
workstation image for all three local projects, proving resource and image reuse
while retaining distinct Cloudmake project identities and remote working trees.
The lower-level image-transition and neutral-anchor restoration contract is
covered separately by `tests/acceptance/codespaces-workstation/run.sh`.

Every command is logged below the evidence directory. The harness stops the
Codespace on success or failure but does not delete its provider-persistent
workspace, allowing bounded post-failure inspection until the Codespace's
configured retention period expires.
