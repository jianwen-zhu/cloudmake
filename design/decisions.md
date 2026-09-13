# Design decisions

This record keeps the consequential decisions that are not obvious from one
implementation file. Stable user behavior is specified under `docs/`; this file
records why the architecture has its present boundaries and what remains open.

## Target delivery

**Accepted:** Cloudmake treats every project target as potentially effectful and
submits it at most once by default. `--idempotent` is an operator assertion about
one invocation only. `--replay-for` is a separate bounded delivery request and
does not change the meaning of `--retry-for`, which covers classified provider
allocation capacity before submission.

**Open:** no current backend proves non-overlapping attempt fencing across every
ambiguous transport boundary. Every backend therefore declares
`target_replay=none` and rejects bounded replay before provider contact. A future
backend may enable replay only after its receipt protocol proves that an earlier
attempt completed or cannot overlap.

## Collection namespace

**Accepted and released:** `.cloudmake/artifacts/` is Cloudmake's transactional
collection destination. The root `.cloudmake/` namespace is excluded from source
synchronization. A project-root `artifacts/` is ordinary project content and is
never moved, deleted, overwritten, symlinked, or dual-written by migration.

Projects upgrading from an older release install both `.gitignore` and
`.cloudmakeignore` protection for `.cloudmake/artifacts/` before changing the
Cloudmake version. They retain any legacy `artifacts/` exclusion for rollback
privacy. The stable behavior is specified under
[source selection](../docs/reference/project-contract.md#source-selection).

## Persistence

**Accepted:** checkpoints are disposable acceleration state. Selected source and
the project Makefile remain authoritative, and complete reconstruction must
remain valid. Managed checkpointing restores the last verified head, reconciles
current source over it, runs the requested target once, and publishes a new
immutable head only after confirmed success. Native-durability backends use the
same `--persist` selection without transferring a checkpoint.

Cloudmake does not infer a safe point inside a running target, capture processes
or kernel state, or treat images, collected artifacts, suspended VMs, and caches
as checkpoint synonyms. The durable architecture is specified in
[`architecture/persistence.md`](architecture/persistence.md).

## Workstation qualification

**Accepted:** the workload contract is the standard OCI, CDI, and Dev Container
workstation contract. Backend declarations describe candidate supply; dynamic
qualification selects one complete realization with evidence or rejects an
unsatisfied standard requirement. Cloudmake does not expose a competing
four-field execution-profile vocabulary.

An adapter may close a provider's realization-mechanism gap, but it may not
discard requested behavior, weaken provider isolation, or gain authority the
backend policy forbids. Candidate order remains backend-defined and observable.
Requested contract, backend declaration, and live evidence remain distinct in
provenance and diagnostics. The durable rationale is in
[`architecture/execution.md`](architecture/execution.md).
