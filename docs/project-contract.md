# Project contract

This document is for developers who want an existing project to run through
cloudmake. It defines the small, provider-independent interface between a
project and the tool. Backend implementation details belong in the
[backend contract](backend-contract.md).

## Required project shape

An executable project-target invocation requires one file:

```text
project-root/
|-- Makefile
`-- ...            # any project-defined layout
```

The `Makefile` must be at the selected project root. Cloudmake does not require
`src/`, `build/`, `output/`, a Git repository, a provider notebook, or a
provider-specific Makefile. It synchronizes selected files while preserving
their paths relative to the project root. A backend may store that synchronized
root in an internal directory named `src`, but that name is invisible to the
project contract.

## Mandatory Make targets

There are no universally mandatory target names.

| Target requirement | When it applies |
| --- | --- |
| The target named by `cloudmake TARGET` | It must exist or be resolvable by the project Makefile for that invocation. |
| The target named by `cloudmake --collect DIR TARGET` | It has the same Make semantics; after success cloudmake collects project-relative `DIR`. |

Every positional target name belongs to the project. For example,
`cloudmake status` invokes the project's `status` target, while
`cloudmake --status` asks the selected provider for its status. Cloudmake does
not attach meaning to any target spelling.

Arbitrary project-specific names work without an escape hatch:

```sh
# Every target below is an example supplied by the project's own Makefile.
cloudmake train
cloudmake benchmark SIZE=large
cloudmake firmware.bin BOARD=rev2
cloudmake --collect dist export-release VERSION=2.0
```

The Colab backend has one opt-in setup hook. If the operator sets
`COLAB_SESSION_PREPARE_TARGET=TARGET`, that project-defined Make target runs
after a fresh or reset session has received the source snapshot, before the
requested target. It must be idempotent because a lost connection can make its
completion ambiguous. Cloudmake records a session-local receipt after confirmed
success and skips the hook only when both its target name and synchronized
source fingerprint still match on the same intact runtime. A source change
conservatively runs the idempotent hook again. This does not create a mandatory
target name or cross-session persistence contract.

## Make-variable interface

Cloudmake injects no Make variables. The remote invocation consists of the
requested target plus only the `NAME=value` arguments supplied by the user:

```sh
# benchmark is a target supplied by the project's Makefile.
cloudmake benchmark MODE=release ITERATIONS=100
```

Those trailing assignments are encoded directly for the remote project
Makefile. Cloudmake's host engine does not evaluate them, even when a project
variable happens to share a name with a backend setting. Configure the backend
through Cloudmake options or host environment variables instead.

The optional Colab session-preparation target receives no user-supplied Make
assignments. It is environment setup, not a substitute execution of the
requested target.

With `-b local`, Cloudmake invokes that same root Makefile directly in the
project directory. It does not enter the backend engine, synchronize files, or
inject variables. This direct invocation is the reference semantics remote
backends are required to preserve.

For `--collect DIR TARGET`, `DIR` is a nonempty project-relative directory with
no `..` components and must not be inside the reserved root `.cloudmake/`
namespace. The project chooses its location and contents through its normal Make
rules; cloudmake neither creates nor clears it. After the target succeeds,
cloudmake archives that directory and transactionally replaces only the local
`project-root/.cloudmake/artifacts/` directory. The project must not create or
manage that local destination.

## Per-invocation target semantics and delivery

Project targets are submitted at most once by default. An operator may assert
that one invocation is idempotent and request a bounded replay policy:

```sh
cloudmake --idempotent --replay-for=30s benchmark SIZE=large
```

`--idempotent` is an assertion about that invocation only. A project file,
shared configuration, Make target, or previous invocation cannot declare it.
`--replay-for` requires the assertion and combines a deadline with a fixed
three-attempt ceiling. It is accepted only when the selected transport can fence
or observe attempts and prove that an earlier attempt cannot still overlap.
No current transport has sufficient proof at every ambiguous boundary, so all
current backends reject bounded replay before provider contact. In particular,
a returned local Make process does not fence background side effects, and a
remote status or connection result does not prove non-overlap.

This rejection is transport-aware without enabling replay: every bundled
backend declares `BACKEND_TARGET_REPLAY := none`, and the launcher consults the
selected descriptor before provider contact. API-1 descriptors that omit the
field default conservatively to `none`; API 1 accepts no enabling value.

A normal nonzero Make result is a confirmed project result and is never
replayed. `--retry-for` remains a separate allocation-capacity control and does
not grant permission to replay a target. Trailing `NAME=value` arguments retain
the exact same parsing and pass-through under every delivery policy.

## Source selection

Cloudmake automatically omits only these root paths:

| Root path | Reason |
| --- | --- |
| `.git/` | Repository metadata is not part of remote execution. |
| `.cloud-state/` | Legacy in-project cloudmake state must not upload itself. |
| `.cloudmake/` | Reserved Cloudmake output, including collected artifacts, must not upload itself. |

All other names, including root `artifacts/`, root `.artifacts/`, `src/`,
`build/`, `.venv/`, cache directories, and notebook output files, have no
built-in meaning and are synchronized normally.
Projects should list unwanted or sensitive paths in `.cloudmakeignore`, one
exclusion pattern per line:

```text
datasets/
*.trace
local-secrets.json
```

Run `cloudmake --sync-dry-run` to inspect the selected files without contacting
the provider.

Projects upgrading from v1.0.1 should complete the
[artifact collection migration preflight](artifact-collection-migration.md)
before their first collection with this candidate.

## Portability boundary

Project recipes run on the selected cloud image and may assume only the tools
that the project itself installs or that the backend documents and checks.
Cloudmake guarantees plain Make dispatch without injected variables. It does not
guarantee a compiler, CUDA version, Python environment, package manager, or
provider-specific filesystem beyond that contract.

Keep portable logic and project-defined configuration in the project Makefile.
