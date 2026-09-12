# Stateless remote Make

This Day 1 tutorial explains Cloudmake's provider-independent execution model.
The normative interfaces remain the [project contract](project-contract.md) and
[backend contract](backend-contract.md).

## Why remote Make exists

Development sometimes needs hardware or a toolchain that is absent from a
laptop. Cloud services provide it through incompatible notebooks, command
clients, upload mechanisms, login flows, and machine lifecycles. A familiar loop
then becomes provider-specific work:

```text
edit locally
  -> select and transfer source
  -> find or start compute
  -> reconstruct the command
  -> retrieve useful output
```

Cloudmake keeps one ordinary automation boundary across those environments: the
project Makefile. The developer chooses a backend; Cloudmake reaches it,
synchronizes the selected source, and invokes the exact project target.

The project-facing principle is intrusion-free adoption. Cloudmake adapts the
execution environment to an existing Make project instead of requiring provider
notebooks, repository credentials, reserved targets, or a prescribed project
layout.

Stateless means source and Make are sufficient to begin again when a provider
replaces a resource. It does not prevent reuse of a currently live session or
saved local backend preferences.

## One command across unlike platforms

A backend identifies one platform through one concrete access path. Different
paths to the same provider are different backends because their failure and
execution boundaries differ.

| Backend | Resource control | Command and transfer path | Reuse boundary |
| --- | --- | --- | --- |
| `local` | Developer | Direct Make; no transfer | Local filesystem |
| `colab-notebook` | Provider | Notebook upload, execution, download | Current live runtime |
| `kaggle-notebook` | Provider | Private notebook batch job | Fresh job per target |
| `codespaces-ssh` | Provider | Provider lifecycle, SSH, rsync | Named stoppable resource |
| `host-ssh` | Host operator | User-managed SSH and rsync | Host policy |

Cloudmake absorbs the different allocation, readiness, transfer, execution, and
cleanup mechanics while keeping the project command `cloudmake TARGET`.
`cloudmake --backends` is the authoritative inventory.

## The one-minute model

Remember six rules:

1. The selected local tree is the source authority.
2. Every positional target belongs to the project Makefile.
3. Cloudmake may start or reuse one backend resource.
4. Source synchronization preserves project-relative paths and needs no remote
   Git credentials.
5. Target delivery is at-most-once unless the operator requests a supported,
   explicitly bounded policy for that invocation.
6. Generated remote state is useful while present but disposable.

```text
local project -> validate source -> select backend -> start or reuse
              -> synchronize -> run exact Make target -> record evidence
              -> optionally collect one selected directory
```

## A small vocabulary

| Term | Meaning |
| --- | --- |
| Project root | Directory containing the authoritative Makefile and selected source. |
| Backend | Adapter for one platform and access path. |
| Resource | Local machine, VM, notebook runtime, or batch job used for execution. |
| Source synchronization | Reconciliation of selected local paths into the remote project tree. |
| Target submission | Point after which the requested Make target may have begun. |
| Provenance | Record of selection, preparation, submission, attempts, and observed result. |
| Collection | Retrieval of one project-chosen output directory after successful execution. |

## The project contract is deliberately small

An executable project needs a Makefile at its selected root:

```text
project-root/
|-- Makefile
`-- ...       # any project-defined layout
```

Cloudmake requires no `src/`, `build/`, or output directory and reserves no
target names:

```sh
cloudmake compile
cloudmake benchmark SIZE=large
cloudmake firmware.bin BOARD=rev2
```

The first positional value is the exact project target. Every following value
must be a `NAME=value` assignment and is passed to Make unchanged. Cloudmake
does not reinterpret a target or inject project variables.

The local backend invokes the same root Makefile directly and is the reference
behavior remote backends must preserve.

## Selecting an execution context

Save the normal backend once, or select one for a single invocation:

```sh
cloudmake --use colab --gpu=T4
cloudmake benchmark SIZE=large
cloudmake -b local verify
```

Saved backend, accelerator, session, and SSH-host choices are local Cloudmake
control state. They are not project source and do not prove that a remote
resource still exists. Cloudmake observes the provider and prints the context it
can establish:

```text
[cloudmake] backend=colab-notebook accelerator=T4 session=my-project resource=reused
```

Use option forms such as `--status`, `--start`, and `--stop` for Cloudmake
operations. Without the leading dashes, those spellings remain project targets.

## Source synchronization without repository credentials

Cloudmake transfers the selected local tree; a remote clone and developer
repository credentials are unnecessary. Three root paths are always outside
source transfer:

- `.git/`, because repository metadata is not execution source;
- `.cloud-state/`, because legacy Cloudmake state must not upload itself; and
- `.cloudmake/`, because the namespace contains Cloudmake-owned output.

Root `artifacts/` and `.artifacts/` are ordinary project source. Add any
project-specific exclusions to `.cloudmakeignore`, then inspect the effective
selection without provider contact:

```sh
cloudmake --sync-dry-run
```

For migration safety, remote synchronization first compares root `artifacts/`
with prior Cloudmake collection receipts. An exact match is blocked as possibly
private downloaded output. Exclude it, change or remove it after review, or
explicitly accept that exact fingerprint with
`--accept-legacy-artifacts-as-source` only when it truly is intended source.

On a reusable resource, synchronization may skip unchanged data. That is a
warm-resource optimization, not a guarantee that generated data survives a
replacement resource.

## Target delivery and uncertainty

Before target submission, Cloudmake can know that Make did not run. After a
submission crosses a remote boundary, a lost connection may hide whether Make
started or completed. Provenance therefore retains exactly three v1 submission
states:

| State | Meaning |
| --- | --- |
| `not_submitted` | Failure occurred before Make could begin. |
| `submitted` | The target was submitted and a result was observed. |
| `ambiguous` | The boundary was crossed but execution cannot be established safely. |

Default delivery is at-most-once. `--retry-for` is only for positively
classified allocation-capacity failures before synchronization and target
submission; it never authorizes target replay.

An operator can state target semantics for one invocation:

```sh
cloudmake --idempotent --replay-for=30s benchmark SIZE=large
```

`--replay-for` requires `--idempotent` and uses both a deadline and a fixed
three-attempt ceiling. The assertion is never read from project files or reused
by a later command. A normal nonzero Make result is never replayed.

Replay also requires transport proof: Cloudmake must fence or observe attempts
and establish that an earlier attempt cannot still overlap. No current backend
has enough evidence at every ambiguous boundary, so all reject `--replay-for`
before provider contact. That decision comes from the selected backend's static
`BACKEND_TARGET_REPLAY := none` declaration; an API-1 descriptor without the
field also defaults to `none`. A returned local Make process does not fence
background side effects, and remote status or connection surfaces do not prove
non-overlap.

If provenance says `target_submission=ambiguous`, inspect provider output, the
printed provenance path, and the project's own external side effects before
running the target again.

## Expected and unexpected failures

A normal project failure preserves Make output and status and adds a concise
summary:

```text
[cloudmake] target 'benchmark' failed with exit status 2
```

Infrastructure failures identify the lifecycle phase and retain the honest
submission state. Unexpected internal failures remain visible; suppressing
noise for an expected Make result must not hide a Cloudmake defect.

Every run record retains the v1 lifecycle and safety fields and additively
records `replay_safe`, target semantics, delivery policy, and ordered attempt
evidence. Assignment names are recorded, while values are represented by
hashes.

## Output and artifact collection are separate

Make output streams for diagnosis. Project files remain in their project-defined
locations unless collection is requested:

```sh
cloudmake --collect dist package-release VERSION=2.0
```

After successful target execution, Cloudmake retrieves `dist` into
`.cloudmake/artifacts/` through bounded, validated, transactional extraction.
It never moves, deletes, overwrites, symlinks, or dual-writes root `artifacts/`.

Before upgrading from v1.0.1 to v1.1.0, follow the
[artifact collection migration preflight](artifact-collection-migration.md).
Projects that might roll back to v1.0.1 must explicitly ignore
`.cloudmake/artifacts/` in both `.gitignore` and `.cloudmakeignore` to prevent an
older version from committing or uploading collected output.

## Daily workflow

```sh
# One-time selection.
cloudmake --use colab --gpu=T4

# Targets supplied by this project's Makefile.
cloudmake bootstrap
cloudmake verify
cloudmake benchmark SIZE=small

# Optional selected output retrieval.
cloudmake --collect results report

# Release a reusable resource when finished.
cloudmake --stop
```

The first target may pay allocation and setup cost. Later targets can reuse the
same live session. If it disappears, the next invocation begins again from the
selected source and Makefile.

The intended outcome is simple: a local Make project can use remote hardware
without becoming a provider-specific project.
