# Cloudmake maintainer design workspace

This directory is for evolving architecture, decisions, qualification evidence,
release procedures, and historical investigations. It is intentionally separate
from the stable user documentation under [`docs/`](../docs/README.md).

Material here may describe an unreleased design, record why a decision was made,
or preserve evidence that should not be mistaken for a current user contract.

## Architecture

- [Stateful workspaces](architecture/stateful-workspaces.md)
- [Execution environments](architecture/execution-environments.md)
- [Colab session resilience](architecture/colab-session-resilience.md)

## Decisions

- [Contract review follow-ups](decisions/contract-review-followups.md)

## Qualification evidence

- [Colab OCI/CDI qualification](qualification/colab-oci-qualification.md)
- [Codespaces native OCI qualification](qualification/codespaces-native-oci.md)

## Historical backend investigations

- [Kaggle notebook](history/kaggle-notebook.md)
- [Paid Colab SSH](history/colab-ssh.md)

## Maintainer operations

- [Release process](releasing.md)
