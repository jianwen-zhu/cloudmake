# UofT teaching release qualification

This document governs the Cloudmake 1.x teaching line used by ECE326 and
ECE467. It is a maintainer qualification record, not a claim that every general
Cloudmake backend is supported by either course.

## Supported course paths

| Course | Guaranteed local path | Guaranteed cloud path |
| --- | --- | --- |
| ECE326 | Local CPU | Colab CPU |
| ECE467 | Local CPU and reference work | Colab GPU |

Codespaces remains an optional general Cloudmake capability. It is outside the
UofT course guarantee. Course projects own their compilers, libraries,
CUDA/toolchain setup, and other environment dependencies through their ordinary
project setup and Make targets. The teaching release does not depend on or
qualify Dev Container functionality. Colab SSH, Kaggle, Lightning, generic SSH
hosts, and other experimental or unqualified providers are also outside this
release's course support boundary.

The course workflow is stateless across provider runtime replacement. Reuse of
objects and setup receipts within the current live Colab runtime is expected,
but a replacement runtime must be reproducible from the authoritative local
project tree. The teaching line does not provide checkpoints, Drive-backed
workspaces, managed restoration, or automatic student-state migration.

## Authentication boundary

1. Google owns account enrollment and Colab entitlement.
2. The official Colab client owns local authorization and its tokens.
3. `cloudmake --doctor` checks the client, its execution compatibility, and
   account access without allocating compute.
4. Cloudmake manages the selected live session and invokes the project's exact
   Make target only after those checks succeed.

Cloudmake must not automate signup, ingest Google tokens, or require credentials
to be copied into the project, generated notebook, hosted CI, or release
evidence. Login, permissions, quota, entitlement, and accelerator capacity are
separate conditions and must be diagnosed separately.

## Candidate release gates

Record the exact candidate commit and selected Colab CLI dependency versions.
All evidence must be sanitized before retention.

- [ ] Complete offline suite passes on supported macOS and Linux hosts.
- [ ] The official Colab CLI installs cleanly and `cloudmake --doctor` verifies
      compatibility and user-owned access without allocating compute.
- [ ] Colab CPU and Colab GPU/T4 smoke tests pass from an already authenticated
      maintainer host.
- [ ] ECE326 Lab 1 setup, public tests, Bottle/benchmark workload, and artifact
      collection pass through the real course workflow.
- [ ] Private paired ECE326 Lab 4 tests and bounded calibration pass without
      copying private course material into Cloudmake or hosted CI.
- [ ] ECE467 onboarding/bootstrap and its applicable CPU, CUDA/device, TileLang,
      GEMM/AXPY, `llm.c`, verification, and artifact paths pass.
- [ ] The same project succeeds after stopping the session and starting with a
      clean replacement Colab runtime, without restored Cloudmake state.
- [ ] A normal local edit, expected nonzero project target, interruption,
      cleanup, and safe retry decision are exercised. An ambiguously submitted
      target is never replayed automatically.
- [ ] Generated notebooks, archives, logs, provenance, tests, hosted CI output,
      and retained evidence contain no credentials or private course data.
- [ ] All temporary compute is stopped and the provider confirms that no test
      session remains active.
- [ ] The exact candidate commit has its CI evidence, checksum, and rollback
      release recorded.

Live tests must run locally with the maintainer's existing provider-owned
authorization. Private course paths may be recorded by identifier and result;
their source and raw output remain outside this repository.

## Semester maintenance policy

During an active semester, the teaching line accepts only security fixes,
provider breakage fixes, and severe correctness fixes. It does not change the
default backend, authentication boundary, persistence model, image, or lifecycle
behavior. Backports from later release lines must be the smallest behavioral fix
for a defect reproduced on 1.x, with focused regression coverage.

Environment dependency changes belong to the applicable course project and its
reproducible setup targets. They do not trigger Dev Container adoption or expand
Cloudmake's provider contract.

Keep the previous known-good 1.x release immediately available for rollback.
Rollback changes the Cloudmake installation only; it must not migrate, delete,
or attempt to restore student project state.
