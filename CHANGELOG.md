# Changelog

All notable changes are recorded here. Cloudmake follows semantic versioning
once a version is published as a GitHub release.

## 2.2.0 - 2026-09-10

- Qualify GitHub Codespaces as the reference CPU remote workstation with
  provider-managed wake/reuse/stop behavior and a stop-persistent `/workspaces`
  tree that avoids checkpoint transfer while remaining disposable and
  rebuildable from source plus Make.
- Add orthogonal backend declarations for lifecycle control, workspace
  durability, and provider-native OCI execution without changing API 1 or the
  target-first CLI surface; existing third-party descriptors receive explicit
  compatibility defaults.
- Make a digest-pinned OCI image the native Codespaces dev-container
  workstation environment. Cloudmake performs one provider rebuild on image
  transition, reuses the same prepared image across targets and stop/start,
  restores the neutral anchor with `--native`, and never launches a nested OCI
  runtime.
- Persist a non-secret Codespace selection locally per project and report
  started versus reused resource state plus rebuilt versus reused native OCI
  environment state in compact execution diagnostics.
- Serialize full operations by Codespace name on the controlling host, record
  pre-rebuild intent for interrupted-transition recovery, fail before source
  synchronization or target submission when preparation is unsuccessful, and
  preserve target exit status through provider-native OCI receipts and normal
  execution provenance.
- Keep Codespaces CPU-only and reject CDI requests before rebuild. The adapter
  adds no privileged mode, capabilities, relaxed security options, host socket,
  or device mount; selected Dev Container image metadata remains trusted input
  under GitHub's provider-native VM boundary.
- Add fake-provider lifecycle, image-transition, recovery, locking, target
  failure, and backward-compatibility coverage plus an opt-in live Codespaces
  workstation gate that restores and stops its resource.
- Harden the live Codespaces transport with current GitHub CLI qualification,
  bounded retries for classified pre-submission control-plane failures, SSH
  connection reuse through a short user-owned control socket, confirmed
  shutdown, and accurate stopped-to-started lifecycle reporting. Project Make
  execution remains once-only and is never covered by these retries.

## 2.1.1 - 2026-09-09

- Inspect digest-pinned images through the selected native runtime after pull,
  so an unrelated host `skopeo` installation cannot add a second registry
  request or change behavior across otherwise equivalent machines.

## 2.1.0 - 2026-09-09

- Add one managed non-native execution surface: digest-pinned OCI images with
  optional standard CDI qualified device requests, while preserving native Make
  as the default and keeping runner, backend, persistence, and source choices
  independent.
- Persist OCI runner selection locally per project with `--image`, `--device`,
  `--no-devices`, and `--native`; project Makefiles remain unchanged and receive
  the same target and user-supplied assignments.
- Validate image digest, Linux platform, runtime, Make availability, and CDI
  device requests before target submission; record architecture comparison and
  selected runtime evidence in the existing single-run provenance while
  allowing the runtime preflight to prove configured architecture emulation.
- Support native Podman, Docker, and nerdctl execution on local and SSH
  backends, with a least-privileged PRoot compatibility fallback and strict CDI
  bind/environment translation.
- Make ordered OCI runtime options an explicit backend property; dynamically
  probe multiple declared host runtimes and fall through when an installed
  client is not operational, without retrying after target submission.
- Add one live-qualified Colab `crun` adapter that materializes OCI rootfs
  layers, adapts the runtime spec to the managed VM's read-only cgroup and
  procfs restrictions, executes Make as UID/GID 65534 with no capabilities and
  `noNewPrivileges`, and supports NVIDIA devices and host drivers through a
  generated CDI specification. Deliberately omit Colab `runc` and bare
  `chroot` alternatives to keep one accelerator-capable maintained profile.
- Retain an experimental Kaggle persistent-workspace adapter that alternates two private
  notebook-output slots, restores the last successful workspace entirely inside
  Kaggle, reconciles current local source, and advances the local head only
  after a successful Make target and validated publication receipt.
- Retain an experimental Kaggle `skopeo` + `umoci` + PRoot OCI profile for trusted computational
  images, including strict `nvidia.com/gpu=all` CDI translation from devices and
  host drivers observed in the actual VM. Cache downloaded runner packages,
  a checksum-pinned current PRoot binary, and the verified OCI layout in the
  private workspace so `session-reuse=no` does not require a cold registry pull
  on every target; discard and reconstruct the derived rootfs to avoid doubling
  checkpoint storage.
- Rehydrate checkpointed virtual-environment links inside the current PRoot
  guest, expose the conventional `/proc` and `/sys` kernel API views required by
  CUDA, and retain UID/GID 65534, empty capabilities, and `noNewPrivileges`.
- Replace backend lifecycle labels with the orthogonal `session-reuse=yes|no`
  property while retaining API-1 lifecycle declarations as compatibility input.
- Add explicit backend status metadata and deprecate Kaggle for remote-
  workstation use after live ECE467 evaluation measured a roughly 14.5 GB
  restore/materialize/publish cycle on every target. Keep the implementation
  available for compatibility and coarse batch experimentation, but remove it
  from release qualification.
- Establish that native workspaces and managed checkpoints are disposable,
  rebuildable acceleration state: source plus Make remain authoritative, and
  persistence must not change target meaning or correctness.
- Distinguish target exit status from OCI infrastructure failure using private
  execution and terminal receipts, including when a project target itself exits
  with `EX_SOFTWARE`/70.
- Extend observed VM characterization with OCI client and CDI evidence while
  retaining active runtime preflight as the compatibility authority.
- Add a digest-pinned ORFS acceptance project whose T4 tool check validates the
  Colab CDI path before real Yosys/OpenROAD stages. The exact `crun` integration
  passed a live non-root T4 smoke test; the full composed replacement-VM
  checkpoint/placement gate remains opt-in because it writes an encrypted
  workspace repository to the user's Google Drive.

## 2.0.0 - 2026-09-07

- Define the storage-neutral Cloudmake 2.0 stateful-workspace and checkpoint
  contract, including source precedence, atomic publication, and failure safety.
- Preserve project-generated files during reusable Colab and SSH source
  reconciliation while removing only paths previously owned by local source.
- Record the Cloudmake 2.0 checkpoint credential-custody contract and gate the
  restic-on-mounted-Drive candidate on non-disclosure and filesystem-reliability
  tests.
- Add opt-in Colab workspace checkpoints backed by an incremental encrypted
  restic repository in the user's Drive. Cloudmake owns the opaque per-project
  repository key in the local OS credential store and sends only per-operation
  encrypted envelopes to the VM; Drive and transient key material are removed
  before project execution.
- Define persistence behavior for every backend: managed checkpoints for native
  Colab, native no-transfer persistence for local and durable SSH workspaces,
  and early rejection for Kaggle batch and Colab SSH. Preserve disabled-by-
  default behavior and the legacy `--checkpoint` option aliases.
- Promote the user-facing abstraction from individual checkpoints to managed
  persistent workspaces, with stable IDs, a local non-secret VM metadata
  registry, explicit list/show/attach/purge operations, and compatibility
  aliases for the earlier checkpoint flags.
- Remove Cloudmake's fixed 50 GiB and one-million-entry workspace ceilings.
  Restore now checks snapshot requirements against the actual free bytes and
  inodes of the allocated VM; Drive and provider capacity remain authoritative.
- Define the durable tool-installation boundary: only the managed project
  workspace is checkpointed, so reusable tool payloads must live there even
  when a project materializes them into an ephemeral execution location.
- Add format-neutral observed VM characterization covering platform, resources,
  privilege, filesystem, namespace, cgroup, device, and accelerator facts.
  Cloudmake 2.0 makes no bundle-compatibility claim; managed OCI/CDI execution
  is explicitly staged as a separate 2.1 capability.
- Freeze the native/OCI runner, persistence, backend, and source axes as
  independent contracts, and add a conservative opt-in ORFS replacement-VM
  acceptance harness for the 2.0 checkpoint gate.
- Pass the live ORFS replacement-VM gate: restore a 3.3 GB workspace in a fresh
  Colab VM, reuse the completed floorplan without rebuilding it, complete
  placement, collect evidence, and publish an incremental successor with about
  4.4 MB of newly added repository data.
- Require a fingerprint-bound success receipt from Colab source reconciliation,
  preventing a provider CLI that masks a remote Python exception from
  dispatching a project target against stale source.

## 1.0.0 - 2026-09-07

- Establish the stable stateless Cloudmake base release. Durable workspaces,
  checkpoints, and cross-VM restoration are outside this release line and begin
  with the stateful 2.0 series.
- Add opt-in, deadline-bounded retry for positively classified Colab allocation
  capacity failures, with exponential backoff, temporary-failure exit status,
  and allocation attempts recorded in the existing run provenance.

## 0.9.1 - 2026-09-07

- Derive the default native Colab session from stable local project identity,
  while preserving explicit `COLAB_SESSION` values and existing v0.9
  `cuda-build` state, with an explicit per-project command to persist migration.
- Replace the two-shot Colab readiness check with configurable deadline-bounded
  polling, cleaning up only a never-ready session created by that invocation
  and never replaying a project target.
- Confirm missing remote Colab control state before treating it as a fresh/reset
  runtime, refuse synchronization when control-state reads are ambiguous, force a
  full stateless source sync, support an optional idempotent session-preparation
  target with source-bound receipts, and record structured lifecycle and
  retry-safety provenance.

## 0.9.0 - 2026-08-28

- Separate expected nonzero Colab Make results from notebook infrastructure
  exceptions, preserving project output and exit status without exposing an
  internal `CalledProcessError` traceback.
- Print compact execution-context banners with the known backend, accelerator,
  resource identity, and started/reused state, and persist explicit accelerator
  selection for subsequent project targets.
- Add the `local` reference backend. Project targets invoke the selected
  project's `Makefile` directly, with no engine dispatch, source transfer,
  session, or injected Make variables, while preserving Cloudmake selection,
  provenance, and target-agnostic artifact collection.
- Define local execution as the semantic baseline that remote backends must
  preserve while adding only transport and provider lifecycle behavior.

## 0.8.0 - 2026-08-25

- Add the `ssh` / `host-ssh` backend and locally persisted `--host` selector for
  incremental execution on any existing user-managed OpenSSH host without
  provisioning, lifecycle control, credential handling, or Git-based transfer.
- Bundle read-only generic, OCI Always Free, and GCP `e2-micro` SSH alias
  templates with installed-runtime listing and rendering commands.
- Document Kaggle's current preinstalled GPU framework/JIT surfaces and clarify
  that its image does not guarantee the standalone `nvcc` compiler.
- Sharpen the project narrative around fragmented accelerator-cloud access and
  distinguish that problem from mature general-purpose CPU cloud tooling.
- State the non-goal principles explicitly, including that Cloudmake preserves
  rather than changes the intended capabilities of backend VMs and runtimes.
- Document transport-aware incremental source synchronization and the separate
  incremental Make behavior available in reusable remote workspaces.

## 0.7.0 - 2026-08-25

- Remove legacy direct-engine `build`, `test`, and `run` shortcuts so every
  project target enters through the single generic dispatch path.
- Make user documentation explicit that example target names are supplied by
  the project's Makefile, and move the internal engine contract to maintainer
  documentation.
- Document Cloudmake's deliberate non-goals and the responsibilities retained
  by projects, provider clients, developers, and cloud services.
- Replace the externally hosted SVG license badge with a portable Apache-2.0
  license link.

## 0.6.0 - 2026-08-25

- Add the `lightning` / `lightning-studio-ssh` backend for persistent CPU and
  GPU Studios through the shared SSH, rsync, remote-Make, and artifact surface.
- Reconcile running Studios onto the requested machine with Lightning's explicit
  switch operation and keep remote state in the documented persistent Studio
  home.
- Keep Lightning login and SSH keys provider-owned, with read-only doctor checks,
  exact SSH-identity references, and offline lifecycle/security regressions.

## 0.5.1 - 2026-08-25

- Remove the hosted live-Colab workflow and its GitHub-secret credential-copy
  path. Live provider gates now run only from a locally authenticated host.
- Add a regression assertion that GitHub workflows never reference repository
  or environment secrets.
- Clarify that Cloudmake delegates authentication to local provider clients and
  never exports, reconstructs, or stores their credentials in hosted CI.

## 0.5.0 - 2026-08-25

- Install the complete Cloudmake runtime instead of only the launcher.
- Add bounded Colab readiness retry without retrying project targets or
  destructively recreating an ambiguously owned session.
- Add artifact file-count, size, archive-size, and expansion-ratio limits.
- Add local execution provenance with hashed Make-assignment values.
- Refuse unmistakable private keys and access tokens before source transfer.
- Prevent failed collection targets from exposing stale artifact archives.
- Add cross-platform CI, scheduled upstream-project checks, a manual live Colab
  gate, and checksummed release automation.
- Add contributor, security, and release policies.

## 0.4.3 - 2026-08-24

- Initial public project with Colab, Kaggle, Codespaces, and paid Colab SSH
  backends; external-project dispatch; artifact collection; resilience controls;
  and real NVIDIA and GPU MODE CUDA regressions.
