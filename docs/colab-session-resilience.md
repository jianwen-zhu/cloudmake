# Colab session resilience design

This design applies specifically to the stateless UofT Colab notebook backend.
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

Only session lookup, creation, reconciliation, and the remote prerequisite
probe occur during readiness. The project target cannot run in that loop. The
deadline uses a monotonic clock, each provider CLI call and probe has its own
timeout, and polling delay is modest and configurable.

A previously selected session that is missing from one provider listing is
rechecked before replacement. An unnamed (`[?]`) listing is never treated as
absence. Once `colab new` has been submitted, a command timeout is saved in a
per-session recovery record and reconciled with bounded polling. A confirmed
named session is adopted. An unnamed, empty, or discovery-error result at the
deadline returns `allocation-deferred`, an exact retry command, and a minimum
delay; retrying is safe because the next invocation resumes reconciliation and
does not immediately create another runtime.

Empty discovery alone is not authoritative failure. Replacement requires the
grace period to expire, successful empty observations in at least two recovery
runs, and the configured observation threshold. Cloudmake then issues at most
one replacement per recovery cooldown and discloses that Colab's missing
allocation idempotency key leaves a duplicate-runtime risk. If that request is
also unresolved, later invocations continue reconciliation and must wait through
the cooldown before another bounded replacement window. Cloudmake adopts a late
named session but never stops an unnamed session. Project target submission is
not part of this recovery loop. Positively classified capacity responses remain
separate and are reconciled before the capacity retry loop continues.

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

The provider executes Python helpers inside a Jupyter kernel, which injects its
`-f <connection-file>` launcher argument. The remote control-state probe accepts
that kernel-only argument without interpreting it. Its local `--parse` and
`--field` receipt interface remains strict and rejects injected or unknown
arguments.

Fresh/reset state invalidates the cached remote fingerprint and forces the
full-archive synchronization path. The local archive is hashed and uploaded to
a content-addressed remote name. The runtime verifies the same SHA-256 digest
before extraction, so a false upload acknowledgement or stale fixed-path file
cannot install old source under a new source receipt. That synchronization
replaces the remote source snapshot. It does not preserve generated files
across a replacement VM.

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

Before execution submission, ordinary preparation and synchronization failures
are retry-safe. Allocation submission is an earlier external side-effect
boundary: if its result cannot yet be reconciled, the project target remains
`not_submitted` and the saved recovery state makes the printed retry command
safe—it reconciles before any bounded replacement. Immediately before the
runner notebook crosses the provider execution boundary, target submission
becomes `ambiguous` and retry safety becomes false. A connection loss after
that point never triggers an automatic target replay. A confirmed target-result
receipt records success or the project's actual Make exit status.

All regression coverage uses the fake Colab client. Live provider execution is
an explicit acceptance activity and is not required by the offline suite.
