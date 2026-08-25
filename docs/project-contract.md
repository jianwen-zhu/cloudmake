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

For `--collect DIR TARGET`, `DIR` is a nonempty project-relative directory with
no `..` components. The project chooses its location and contents through its
normal Make rules; cloudmake neither creates nor clears it. After the target
succeeds, cloudmake archives that directory and transactionally replaces the
local `project-root/artifacts/` directory. The project must not create or manage
that local destination.

## Source selection

Cloudmake automatically omits only these root paths:

| Root path | Reason |
| --- | --- |
| `.git/` | Repository metadata is not part of remote execution. |
| `.cloud-state/` | Legacy in-project cloudmake state must not upload itself. |
| `artifacts/` | Cloudmake-owned local collection output must not be sent back as source. |

All other names, including `src/`, `build/`, `.venv/`, cache directories, and
notebook output files, have no built-in meaning and are synchronized normally.
Projects should list unwanted or sensitive paths in `.cloudmakeignore`, one
exclusion pattern per line:

```text
datasets/
*.trace
local-secrets.json
```

Run `cloudmake --sync-dry-run` to inspect the selected files without contacting
the provider.

## Portability boundary

Project recipes run on the selected cloud image and may assume only the tools
that the project itself installs or that the backend documents and checks.
Cloudmake guarantees plain Make dispatch without injected variables. It does not
guarantee a compiler, CUDA version, Python environment, package manager, or
provider-specific filesystem beyond that contract.

Keep portable logic and project-defined configuration in the project Makefile.
