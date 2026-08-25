# Changelog

All notable changes are recorded here. Cloudmake follows semantic versioning
once a version is published as a GitHub release.

## Unreleased

- Add the `ssh` / `host-ssh` backend and locally persisted `--host` selector for
  incremental execution on any existing user-managed OpenSSH host without
  provisioning, lifecycle control, credential handling, or Git-based transfer.
- Document Kaggle's current preinstalled GPU framework/JIT surfaces and clarify
  that its image does not guarantee the standalone `nvcc` compiler.
- Sharpen the project narrative around fragmented accelerator-cloud access and
  distinguish that problem from mature general-purpose CPU cloud tooling.
- State the non-goal principles explicitly, including that Cloudmake preserves
  rather than changes the intended capabilities of backend VMs and runtimes.

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
