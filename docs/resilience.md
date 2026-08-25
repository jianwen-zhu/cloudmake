# Resilience and recovery

Cloudmake moves source into short-lived or reusable cloud environments, so it
must handle interrupted transfers, expired sessions, concurrent commands, and
unexpectedly reused workspaces without damaging a project. This document
describes those safeguards and the controls available when recovery is needed.

## Project ownership

Before synchronization, cloudmake records a stable project identity derived
from the canonical local path and host. Reusable remote workspaces carry the
corresponding owner record. If another project attempts to use that workspace,
cloudmake stops before replacing source or running `rsync --delete`.

An intentional reassignment requires a conspicuous one-time override:

```sh
# PROJECT_TARGET is supplied by the project's Makefile.
CLOUDMAKE_ADOPT=1 cloudmake PROJECT_TARGET
```

Do not use adoption merely to bypass an unexpected error. First inspect the old
source path and host reported by cloudmake. Owner records contain provenance,
not credentials, but are copied to the selected workspace or private notebook.

Local owner and state files are written atomically with private file
permissions. Corrupt identity state is refused rather than silently replaced.

## Source selection and preflight

Cloudmake creates a common source manifest for notebook archives and SSH
transfers. Automatic exclusions are intentionally limited to root `.git/`,
`.cloud-state/`, and `artifacts/`: repository metadata, legacy in-tree tool
state, and downloaded output. Other names carry no built-in meaning, so a
project may freely use directories such as `src/`, `build/`, or `.venv/`.

Projects can add exclusions in `.cloudmakeignore`, one glob per line. Blank
lines and `#` comments are allowed:

```text
datasets/
*.trace
local-secrets.json
```

Negated patterns are deliberately unsupported. This keeps archive and rsync
selection consistent instead of allowing the two transports to interpret the
same file differently.

Preview a source change without authenticating, allocating compute, or
contacting a provider:

```sh
cloudmake --sync-dry-run
```

The report compares the selected tree with the last successful manifest and
lists added, modified, and deleted paths. Selection warns above 25 MiB by
default. `SOURCE_WARN_MB` changes the warning threshold; a nonzero
`SOURCE_MAX_MB` rejects an oversized selection before creating an archive or
starting a provider operation.

Special files are rejected. A symbolic link is accepted only when it resolves
inside the project, preventing an archive from unintentionally capturing data
outside the selected tree.

## Concurrency and locks

Mutating targets are serialized with a per-backend, per-resource local lock. A
process crash releases this operating-system lock automatically.

SSH synchronization and execution also use a token-protected lock on the remote
workspace. Only the holder's token can release it. If a client disappears, the
lock becomes reclaimable after `REMOTE_LOCK_STALE` seconds. This prevents two
local commands from concurrently replacing source or invoking Make in the same
workspace while still permitting recovery after an abandoned connection.

## Transactional updates

State files, manifests, and source snapshots are written to temporary paths and
renamed only after validation succeeds.

On Colab, cloudmake extracts a source archive into a staging directory and swaps
it into place only after every archive member passes path, link, and type checks.
Kaggle notebooks apply the same archive validation before execution.

Downloaded artifact archives are treated as untrusted. Absolute paths,
directory traversal, links, devices, and other special files are rejected. New
artifacts are extracted into a staging directory, so an invalid or interrupted
download leaves the previous `artifacts/` directory intact.

Extraction is rejected before writing when configured file-count, total-size,
per-file-size, compressed-size, or expansion-ratio budgets are exceeded. A
collection run deletes its prior remote artifact archive before invoking the
project target, so a failed target cannot make an older archive appear to be its
result.

Project-generated files remain wherever the project Makefile places them. A
reusable backend retains them while its synchronized project workspace remains
valid; a batch backend starts from a fresh source snapshot.

## Readiness checks

Every compute operation has two readiness stages:

1. Host-side `prerequisites` and `doctor` validate commands, settings,
   authentication, and read-only provider access before allocation.
2. When a VM is reachable, cloudmake checks required remote commands before
   transferring source. Batch notebooks perform this check at the start of the
   submitted job.

This catches a missing Make, `tar`, `rsync`, compiler, or provider client near
the boundary where the problem can be explained clearly.

## Provider reconciliation

Saved local state is not treated as proof that compute still exists. Colab
sessions are reconciled through `colab sessions`; Codespaces is probed through
`gh`; and Lightning Studios are reconciled through the authenticated Studio
list. If generated SSH configuration has expired, cloudmake refreshes it once
after a failed connection.

Colab retries its non-mutating remote-readiness probe once. If the named kernel
remains unreachable, Cloudmake refuses automatic recreation because it cannot
verify remote ownership through the broken connection. The operator must inspect
status and explicitly stop the session before retrying. Cloudmake never applies
readiness retries to a project target.

Cloudmake does not blindly retry target execution or a mutating notebook
submission. An ambiguous failure may already have started work, so automatic
repetition could produce duplicate jobs or side effects.

Provider-specific status is retained and followed by one normalized state:

- `absent`
- `starting`
- `ready`
- `running`
- `succeeded`
- `failed`
- `stopped`
- `unknown`

`unknown` means the provider response was recognized as neither a successful
nor a failed terminal state; it is not silently treated as success.

Launcher executions retain private local JSON provenance under the project's
external Cloudmake state directory. Records include the source and collected
artifact fingerprints, target, backend, resource, timestamps, and result. Make
assignment values are hashed rather than copied. Use `cloudmake --history` to
locate and summarize recent records.

## Recovery checklist

When an operation fails:

1. Run `cloudmake -b <name> --status` and read the provider-specific output.
2. Run `cloudmake -b <name> --doctor` to recheck local authentication and access.
3. Run `cloudmake --sync-dry-run` to inspect the selected source and pending
   changes.
4. If ownership differs, verify the reported project path and host before using
   `CLOUDMAKE_ADOPT=1` in the host environment.
5. If a remote lock is abandoned, wait for or deliberately adjust
   `REMOTE_LOCK_STALE`; do not delete an active holder's lock.
6. Re-run a mutating target only after determining whether the provider already
   accepted the earlier request.
