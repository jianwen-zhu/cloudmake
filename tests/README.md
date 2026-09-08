# Test suite

The default suite is deliberately offline. Provider integration tests put fake
`colab`, `kaggle`, `gh`, `lightning`, `ssh`, and `rsync` executables at the front
of `PATH`; they never allocate cloud compute or use account credentials.

Run everything that is implemented today:

```sh
python3 -m pip install -r requirements-test.txt
python3 -m pytest
```

If pytest is installed by a separate environment manager, invoking its `pytest`
executable directly is equivalent.

Run one layer:

```sh
python3 -m pytest tests/test_source_fingerprint.py
python3 -m pytest tests/test_resilience.py
python3 -m pytest tests/test_notebooks.py
python3 -m pytest tests/test_colab_allocate.py
python3 -m pytest tests/test_target_result.py
python3 -m pytest tests/test_vm_capabilities.py
python3 -m pytest -m integration
```

## Real GitHub CUDA projects

Cloudmake carries small Makefile overlays for two public course projects:

- NVIDIA's CUDA C++ Execution Spaces lesson gains `build`, `run`, and `clean`;
- GPU MODE's vector-addition Makefile gains a `run` target while preserving its
  existing default build.

The overlays are covered offline with fake compilers. To also sparse-clone the
pinned upstream revisions, apply the overlays, and exercise their targets:

```sh
CLOUDMAKE_TEST_REAL_GITHUB=1 python3 -m pytest \
  tests/test_real_github_projects.py -m real_github
```

This invokes `tests/real_projects/prepare.sh`, which prints the two prepared
project directories. The clones are revision-pinned so an upstream change cannot
silently alter a regression run.

The live Colab gate is intentionally local-only because it allocates GPU compute
through the workstation's existing Colab CLI authentication. It clones both
projects, runs the overlaid `run` targets on separate T4 sessions, and stops each
session in a `finally` block:

```sh
CLOUDMAKE_TEST_LIVE_COLAB=1 python3 -m pytest \
  tests/test_real_github_projects.py -m live_cloud
```

Do not copy Colab configuration or tokens into GitHub Actions. The repository
also provides a local-only Lightning T4 gate over the same two pinned projects.
It uses the Lightning client's existing login and provider-owned SSH key, then
stops the Studio without deleting its persistent filesystem:

```sh
export LIGHTNING_TEAMSPACE=OWNER/TEAMSPACE
export LIGHTNING_STUDIO=cloudmake-dev
CLOUDMAKE_TEST_LIVE_LIGHTNING=1 python3 -m pytest \
  tests/test_real_github_projects.py -m live_cloud
```

Do not copy Lightning configuration, login tokens, or SSH keys into GitHub
Actions. The repository
provides two credential-free hosted automation layers:

- `CI` runs the offline suite on supported macOS/Linux and Python combinations;
- `Upstream compatibility` runs the pinned public CUDA projects weekly or on
  demand without allocating cloud compute.

## ORFS persistent-workspace acceptance

The final Cloudmake 2.0 persistence gate is opt-in and deliberately separate
from the offline suite. It runs two project-provided ORFS stage targets across a
destroyed and replacement Colab VM, checks Cloudmake restore/publication
evidence, and collects project-owned proof that the second stage consumed the
first stage without rebuilding it:

```sh
export COLAB_SESSION=cloudmake-orfs-acceptance
export CLOUDMAKE_TEST_LIVE_ORFS_CHECKPOINT=1
tests/acceptance/orfs-checkpoint/run.sh \
  /path/to/orfs-project PROJECT_STAGE_1 PROJECT_STAGE_2 evidence
```

The prepared ORFS project owns its tool acquisition, launcher, stage checks,
and target names. See the [gate contract](acceptance/orfs-checkpoint/README.md).
The harness leaves the session intact after any failed or ambiguous operation.

`tests/contract/` exercises the public `cloudmake` launcher interface, including
configuration precedence, aliases, external project isolation, arbitrary target
dispatch, zero reserved project names, target-agnostic artifact collection,
option-only lifecycle routing, opaque project-assignment transport, and read-only
operations.

Test coverage is organized around observable behavior rather than provider SDK
internals:

- deterministic source fingerprinting and exclusions;
- archive safety and atomic Colab source replacement;
- fingerprint-bound Colab synchronization receipts that prevent a provider CLI
  from masking a remote synchronization exception and dispatching stale source;
- adversarial Colab control-state downloads: a present but unreadable owner or
  fingerprint is never treated as absence, never triggers source replacement,
  and keeps the project target unsubmitted;
- source-bound preparation receipts plus distinct upload/install failure
  provenance;
- Kaggle notebook generation, metadata, bounded status polling, and failure
  handling;
- executable Colab and Kaggle notebooks against temporary projects;
- Colab project-failure receipts, concise diagnostics, retained infrastructure
  tracebacks, and started-versus-reused execution context;
- Colab capacity classification, bounded allocation backoff, temporary-failure
  deadlines, immediate interruption, fail-fast compatibility, and at-most-once
  target dispatch;
- opt-in Colab persistent-workspace selection and provenance, restore/target/publication
  ordering, fail-closed restore and cleanup behavior, no publication after a
  failed target, OS credential-store key reuse, and encrypted-envelope
  non-disclosure;
- persistence-mode behavior across every backend: checkpoint transfer on native
  Colab, no-transfer native storage on local and durable SSH workspaces, early
  rejection on ephemeral Kaggle/Colab SSH, legacy option aliases, and disabled-
  by-default target compatibility;
- stable workspace identity independent of project path, local metadata
  list/show, explicit attachment, force-gated purge, and restore capacity checks
  against the allocated VM rather than a fixed Cloudmake ceiling;
- bounded local and Colab environment characterization with explicit observed
  platform, resource, privilege, filesystem, isolation, device, and accelerator
  evidence, without inferred application-format compatibility;
- ownership-aware checkpoint links: strict uploaded/source-owned links,
  non-followed generated package/rootfs links, rejected special entries and
  symlinked control records, and generated-link preservation across source sync;
- default Colab compatibility with no Drive, credential-store, restore, or
  publication side effects and unchanged project-target argument dispatch;
- portable Make build, test, run, package, clean, and incremental behavior;
- reproducible Makefile overlays for pinned NVIDIA and GPU MODE CUDA lessons;
- backend lifecycle and command construction through fake provider clients;
- Lightning Studio start/reuse/machine-switch/stop behavior, persistent paths,
  exact key references, and the absence of Git-based project transfer;
- user-managed host SSH synchronization, lifecycle preservation, local alias
  validation, and absence of provider or credential configuration;
- installed generic, OCI, and GCP host-template discovery and safe rendering;
- per-backend commands, settings, Python version, authentication probes, and
  installation guidance;
- project ownership, atomic state, local and remote locks, stale recovery, and
  live-session reconciliation;
- shared source manifests, dry-run plans, ignore rules, source-size gates, and
  backend capability contracts;
- safe transactional artifact replacement and status normalization; and
- artifact resource budgets, secret-transfer refusal, execution provenance, and
  fresh installed-runtime behavior; and
- the launcher against external projects through Colab, Kaggle, and the common
  SSH transport, including lossless Make-variable passthrough without host-engine
  interpretation.
