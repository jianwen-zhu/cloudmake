# Backend contract

Cloudmake backends adapt different provider lifecycles and transports to one
execution model: synchronize a local working tree, invoke an ordinary Make
target remotely, and retrieve output. This document is for cloudmake backend
authors and maintainers. Project developers should instead read the
[project contract](project-contract.md).

## Project boundary

Every backend must implement the separate [project contract](project-contract.md)
without adding provider-specific project requirements. In particular, a
backend must preserve project-relative paths, dispatch the exact requested Make
target without injecting Make variables, and avoid requiring a provider notebook
or provider-specific Makefile in the project.

Trailing project `NAME=value` arguments must remain opaque to the host engine.
A backend reads its own settings from explicit launcher options or the host
environment, never by interpreting the project's assignment namespace.

Backend lifecycle operations are selected through launcher options such as
`--status` and `--fetch`. A positional name with the same spelling remains a
project target. The target-agnostic `--collect DIR TARGET` operation must validate
`DIR` as project-relative, invoke the exact requested target, archive that
existing directory after success, and transactionally replace the local
`artifacts/` directory.

## Names and transports

User aliases are short; canonical names identify transport explicitly:

| User alias | Canonical backend | Transport |
| --- | --- | --- |
| `colab` | `colab-notebook` | Native Colab contents and kernel APIs |
| `kaggle` | `kaggle-notebook` | Private Kaggle notebook version |
| `codespaces` | `codespaces-ssh` | SSH and rsync |
| `colab-ssh` | `colab-ssh` | SSH and rsync |
| `lightning` | `lightning-studio-ssh` | SSH and rsync |

An alias must not silently change transport. In particular, `colab` always
means native notebook access and never falls back to SSH.

## Backend descriptor

Each backend declares:

- the supported backend API version;
- a canonical backend name;
- a lifecycle, either `session` or `batch`;
- an ordered set of capabilities; and
- a resource identifier suitable for local serialization.

The shared core validates the descriptor before running an operational target.
Inspect the resolved descriptor with:

```sh
make BACKEND=colab-notebook backend-info
```

Capabilities describe real behavior rather than provider branding. Examples
include synchronization, execution, artifact retrieval, status, opening a web
interface, stopping reusable compute, and an interactive shell. A backend must
not advertise a shell merely because its provider has a browser terminal.

## Lifecycle semantics

A `session` backend may start or reuse a named VM. It must reconcile cached
identity with live provider state before use and expose a meaningful `stop`
operation.

A `batch` backend submits a fresh job for each operational target. `start` may
validate readiness, but it must not pretend to create a reusable VM. `stop` may
be a documented no-op when the provider ends jobs automatically.

The engine's common lifecycle operations are `start`, `sync`, `status`, `fetch`,
`open`, `shell`, and `stop`; the launcher exposes them as long options. A
positional name with the same spelling remains a project target. Unsupported
operation options fail clearly rather than changing meaning per backend.

## Transport responsibilities

Every transport must:

1. gate operations on host prerequisites and a read-only provider probe;
2. use the common source scanner, manifest, exclusions, and size limits;
3. verify project ownership before replacing source;
4. serialize mutations for the selected resource;
5. verify remote execution prerequisites when the environment becomes
   reachable;
6. invoke the selected target through plain Make;
7. retrieve artifacts with safe transactional extraction; and
8. report both provider detail and a normalized cloudmake status.

Notebook transports package the selected source and execute provider control
cells. The generated notebook and control code belong to cloudmake rather than
the project. A reusable notebook session can skip upload when the manifest is
unchanged; a batch provider may reuse its local archive but still submits a new
job.

SSH transports synchronize incrementally with rsync and invoke Make over the
same SSH execution surface. Provider backends supply connection discovery and
lifecycle behavior. The transport must check ownership before any
`rsync --delete`, and synchronize the uploaded project independently of any
anchor repository checked out by the provider.

## State boundary

Generated preferences, fingerprints, notebooks, archives, locks, SSH
configuration, and provider output are tool state. The launcher stores
them in user configuration, state, and cache directories keyed by the local
project identity. They do not belong in either the cloudmake repository or the
actual project repository.

Downloaded project output is different: cloudmake creates and owns the local
project `artifacts/` directory as the materialized result of `--collect`.

Configuration precedence is:

```text
command line
  > environment variables
  > per-project local preferences
  > optional shared project configuration
  > global user preferences
  > backend defaults
```

Provider authentication stays with the provider's own client. A backend should
reference credentials or SSH identities when needed, never copy them into
project state or a source archive.

## Adding a backend

A new backend should first choose its honest lifecycle and transport. Reuse a
shared transport when its synchronization and execution semantics match; add a
new transport only when the provider surface genuinely differs.

The implementation is complete when it has:

1. a canonical, transport-explicit name and optional human-friendly alias;
2. a valid descriptor and capability set;
3. host prerequisite and read-only authentication checks;
4. live status reconciliation;
5. source ownership, locking, transfer, and remote prerequisite handling;
6. target execution and safe artifact retrieval;
7. normalized status mappings; and
8. offline fake-provider tests for successful and failed operations, including
   proof that it does not cross architecture boundaries such as cloning the
   user's project or using SSH from a native-notebook backend.

See [Resilience and recovery](resilience.md) for the required failure behavior
and [Security model](security.md) for trust boundaries.
