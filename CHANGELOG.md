# Changelog

All notable changes are recorded here. Cloudmake follows semantic versioning
once a version is published as a GitHub release.

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
