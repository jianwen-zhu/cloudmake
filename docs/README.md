# Cloudmake user documentation

This directory contains the documentation shipped as the stable user contract.
It explains how to use a released Cloudmake version and what behavior projects
and backend integrations may rely on.

## Tutorials

Cloudmake's major capabilities form a four-day learning path. Each tutorial
stands alone, while the sequence adds one concern at a time.

| Day | Release step | Major subject | Central question |
| --- | --- | --- | --- |
| [Day 1](tutorials/stateless-remote-make.md) | Cloudmake 1.x | Stateless remote Make | How can an unchanged local Make project run on remote hardware? |
| [Day 2](tutorials/workspace-persistence-landscape.md) | Cloudmake 2.0 | Managed checkpoints | How can useful build artifacts survive disposable compute without becoming project authority? |
| [Day 3](tutorials/devcontainer-execution-landscape.md) | Cloudmake 2.1–2.4 | Dev Container workstations | How can one workstation contract run across unequal backends with the least host privilege? |
| Day 4 | Cloudmake 3.x | Security model | How can remote execution preserve identity, credential custody, trust, and least authority? |

```text
remote Make
  -> retain useful build state
  -> supply a portable development workstation
  -> secure identities, credentials, and trust boundaries
```

## Guides

- [Artifact collection migration](guides/artifact-collection-migration.md)
- [Google Compute Engine backend](guides/gcp-backend.md)

## Reference

- [Project contract](reference/project-contract.md)
- [Backend contract](reference/backend-contract.md)
- [Resilience and recovery](reference/resilience.md)
- [Security model](reference/security.md)
- [OCI/CDI runner](reference/oci-runner.md)
- [Dev Container workstations](reference/devcontainers.md)
- [Dev Container workstation contract](reference/devcontainer-contract.md)

The user documentation describes released behavior. Design proposals,
qualification evidence, historical experiments, and maintainer release notes
live separately under [`design/`](../design/README.md).
