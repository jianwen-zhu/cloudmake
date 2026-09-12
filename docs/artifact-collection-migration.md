# Artifact collection migration preflight

This candidate changes Cloudmake's one owned project-root output from
`artifacts/` to `.cloudmake/artifacts/` and reserves the complete root
`.cloudmake/` namespace. Root `artifacts/` and `.artifacts/` are ordinary project
source again.

Cloudmake never migrates, deletes, overwrites, symlinks, or dual-writes an
existing `artifacts/` directory. A successful collection creates or
transactionally replaces only `.cloudmake/artifacts/`. Failed validation or
extraction preserves the previous valid collection there.

Before adopting this candidate:

1. Confirm that the project does not already use root `.cloudmake/` for project
   source or a symlink. Rename any project-owned use explicitly; Cloudmake will
   refuse unsafe collection destinations rather than move them.
2. Decide whether an existing `artifacts/` or `.artifacts/` directory is project
   source. Cloudmake will begin synchronizing and fingerprinting it unless the
   project explicitly excludes it in `.cloudmakeignore`.
3. Cloudmake checks external run provenance before remote synchronization. If
   root `artifacts/` exactly matches a known prior Cloudmake collection receipt,
   it blocks before the backend engine or provider client runs.
4. Run `cloudmake --sync-dry-run` and review the newly selected paths before any
   provider operation.
5. Resolve a blocked legacy collection in one of three explicit ways:

   - add `/artifacts/` to `.cloudmakeignore` if it must remain local;
   - move, remove, or change it after deciding what the project owns; or
   - if the exact contents really are intended project source, run the remote
     command once with `--accept-legacy-artifacts-as-source`. Cloudmake stores a
     private local acceptance bound to that exact fingerprint.
6. Add `.cloudmake/artifacts/` to both `.gitignore` and `.cloudmakeignore`.

The sixth step is required for projects that may roll back to v1.0.1. This is a
privacy boundary, not housekeeping: this candidate excludes the reserved
`.cloudmake/` namespace automatically, but v1.0.1 does not. Without an explicit
`.cloudmakeignore` entry, a rollback can select previously collected output for
remote upload. Without the `.gitignore` entry, it can also be committed by
mistake.

Recommended entries:

```text
# .gitignore
.cloudmake/artifacts/
```

```text
# .cloudmakeignore
.cloudmake/artifacts/
```

Rollback does not move collected output back to `artifacts/`. Copy or reconcile
files manually only after reviewing their contents and deciding which directory
the project owns.

Do not use `--accept-legacy-artifacts-as-source` merely to bypass the warning.
It means the matching downloaded contents are intentionally uploadable project
source. A forged, incomplete, path-mismatched, or fingerprint-mismatched receipt
does not establish legacy identity and is never presented as positive evidence.
