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

Requested targets use at-most-once delivery by default. The invocation-only
`--idempotent` declaration does not itself authorize another submission, and
every backend in this release declares `target-replay=none`. UofT workflows do
not use `--idempotent` or `--replay-for`. If submission is ambiguous, retain the
provenance record, do not resubmit, and escalate to course staff.

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

## Course migration contract

Do not move the published `uoft` branch or repin either course until the
candidate is immutable and the applicable course gate below passes. Both course
repositories must explicitly ignore `.cloudmake/artifacts/` in `.gitignore` and
`.cloudmakeignore`, while retaining their legacy `/artifacts/` exclusion during
the rollback window. This is a privacy requirement because v1.0.1 does not
automatically exclude `.cloudmake/`.

Do not teach `--accept-legacy-artifacts-as-source` as a migration shortcut.
Inspect old root `artifacts/` contents and then archive, remove, change, or
explicitly exclude them according to project ownership. Regenerate course
releases from their authoritative sources; never hand-edit generated release
trees.

ECE326 migration must also:

- exclude `.cloudmake/` from leaderboard candidate digests and paired payloads;
- reject `.cloudmake/` content in student release archives while retaining the
  `.cloudmakeignore` control file;
- update quickstart, tutorial-plan, grading, leaderboard, onboarding, and
  release-validation text together with the version, commit, and archive digest;
- keep the official private paired benchmark at-most-once, with no manual retry
  after an ambiguous submission.

ECE467 migration must also:

- exclude generated `release-student/` and `release-grader/` trees from remote
  synchronization;
- update the Makefile host check, help, README, and release metadata together;
- persist `COLAB_SESSION` before selecting the Colab/T4 environment;
- describe repeated `bootstrap` as separate operator requests, not target
  replay.

## Candidate release gates

Record the exact candidate commit and selected Colab CLI dependency versions.
All evidence must be sanitized before retention.

- [ ] Complete offline suite passes on supported macOS and Linux hosts.
- [ ] The official Colab CLI installs cleanly and `cloudmake --doctor` verifies
      compatibility and user-owned access without allocating compute.
- [ ] Colab CPU and Colab GPU/T4 smoke tests pass from an already authenticated
      maintainer host.
- [ ] ECE326 Lab 1 setup, public tests, Bottle/benchmark workload, and artifact
      collection pass through one fresh Colab CPU session. Collection lands only
      in `.cloudmake/artifacts/`, and provenance records one submitted attempt.
- [ ] Private paired ECE326 Lab 4 tests and bounded calibration pass without
      copying private course material into Cloudmake or hosted CI. The official
      paired target is submitted exactly once in a separate fresh CPU session;
      ambiguity fails the release gate without resubmission.
- [ ] ECE467 onboarding/bootstrap and its applicable CPU, CUDA/device, TileLang,
      GEMM/AXPY, `llm.c`, verification, and artifact paths pass in one bounded
      T4 session. Two explicit `bootstrap` requests reuse one runtime identity,
      the selected 19-check regression passes, and the old root artifact remains
      byte-for-byte unchanged.
- [ ] The same project succeeds after stopping the session and starting with a
      clean replacement Colab runtime, without restored Cloudmake state. ECE467
      observes a new runtime identity and passes bootstrap, verify, and the
      bounded TileLang AXPY smoke test.
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
