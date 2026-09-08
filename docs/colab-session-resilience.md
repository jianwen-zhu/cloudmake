# Colab session resilience design (v1.0.0)

This design applies specifically to the stateless v1.0.0 Colab notebook backend.
It improves the safety of reusable live sessions without introducing durable
workspaces, checkpoints, or cross-VM restoration.

## Session identity

The launcher derives the default session name from a sanitized project basename
and the first eight characters of a stable project key. The key hashes the
canonical local path together with the host identity. The result is readable,
stable on that host, and unlikely to collide with another project.

An explicit `COLAB_SESSION` always wins. If the project's external Cloudmake
state already contains `colab-notebook/cuda-build`, the launcher keeps the old
v0.9 default and prints the persistent migration command. The operator selects
a durable per-project replacement with
`COLAB_SESSION=NAME cloudmake --use colab`. A normal environment override stays
unpersisted. Before changing the saved selection, the operator inspects
`cuda-build` with `COLAB_SESSION=cuda-build cloudmake -b colab --status` and,
only when it is no longer needed, releases it with the corresponding `--stop`
command. Shared explicit names remain possible, but remote ownership checking
prevents accidental replacement.

## Pre-submission state machine

The Colab lifecycle moves through these states:

```text
session lookup -> create or reuse -> bounded readiness polling
               -> ownership classification -> stateless source sync
               -> optional idempotent preparation -> target submission
```

Only session lookup, creation, and the remote prerequisite probe occur during
readiness. The project target cannot run in that loop. The deadline uses a
monotonic clock, each probe has its own timeout, and polling delay is modest and
configurable.

Positive creation evidence is a successful `colab new` performed by the current
invocation. If that new session never becomes ready, it can be stopped safely.
No other session is automatically destroyed or recreated.

## Runtime classification and stateless recovery

The provider CLI does not expose a stable runtime-instance identifier, so
Cloudmake uses its remote ownership and source-fingerprint files as control
state. It first runs a non-mutating remote existence probe. Only a successful
probe can establish that a file is absent; a failed probe or a failed download
of a file reported present is ambiguous and stops before synchronization:

- `same`: the reachable workspace has the expected owner and control state;
- `fresh`: this invocation created the session and remote ownership is absent;
- `reset`: the named session was reused but ownership or fingerprint state is
  absent;
- `foreign`: ownership belongs to another project;
- `unreachable`: the runtime cannot be inspected, so its identity is ambiguous.

Fresh/reset state invalidates the cached remote fingerprint and forces the v0.9
full-archive synchronization path. That synchronization replaces the remote
source snapshot. It does not preserve generated files across a replacement VM.

`COLAB_SESSION_PREPARE_TARGET` optionally names a project-defined, idempotent
Make target. Cloudmake runs it after fresh/reset synchronization, records a
receipt only after confirmed success, and skips it while the same live session
retains a receipt bound to both the target name and synchronized source
fingerprint. Source changes conservatively rerun the idempotent preparation.
The requested target is uploaded only afterward. Receipt upload and installation
failures retain `not_submitted` for the requested target and have distinct
machine-readable failure codes.

## Failure provenance and replay boundary

Operation state is atomically recorded outside the project tree. Colab run
provenance includes:

- lifecycle phase;
- normalized provider state;
- runtime classification;
- whether the current invocation created the session;
- submission state: `not_submitted`, `submitted`, or `ambiguous`;
- retry safety and a machine-readable failure code.

Before execution submission, failures are retry-safe. Immediately before the
runner notebook crosses the provider execution boundary, submission becomes
`ambiguous` and retry safety becomes false. A connection loss after that point
never triggers an automatic target replay. A confirmed target-result receipt
records success or the project's actual Make exit status.

All regression coverage uses the fake Colab client. Live provider execution is
an explicit acceptance activity and is not required by the offline suite.
