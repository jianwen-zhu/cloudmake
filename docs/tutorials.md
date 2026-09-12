# Remote workstation tutorials

Cloudmake's major releases form a four-day learning path. Each tutorial stands
on its own, while the sequence adds one capability at a time.

| Day | Release step | Major subject | Central question |
| --- | --- | --- | --- |
| [Day 1](stateless-remote-make.md) | Cloudmake 1.x | Stateless remote Make | How can an unchanged local Make project run on remote hardware? |
| [Day 2](workspace-persistence-landscape.md) | Cloudmake 2.0 | Workspace persistence and checkpointing | How can useful mutable work survive disposable compute without becoming project authority? |
| [Day 3](devcontainer-execution-landscape.md) | Cloudmake 2.1–2.4 | OCI/CDI bundles and Dev Container workstations | How can a standard tool environment run across unequal backends with the least host privilege? |
| Day 4 | Cloudmake 3.x | Security model | How can remote execution preserve identity, credential custody, trust, and least authority? |

The progression is deliberate:

```text
remote Make
  -> retain mutable work
  -> supply a portable development workstation
  -> secure its identities, credentials, and trust boundaries
```

Backend additions such as Codespaces and GCP improve where these capabilities
run. They do not add another project-facing abstraction, so they do not require
another tutorial day.

Day 4 is being developed with the Cloudmake 3.x security model on its separate
branch. It will become a link here only when that work joins the release line.

The tutorials explain concepts and tradeoffs. The README and contract documents
remain authoritative for exact command behavior and supported fields.
