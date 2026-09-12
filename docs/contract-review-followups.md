# Contract review follow-ups

This maintainer list records design findings that must survive the tutorial
review even when they are too consequential to implement as prose cleanup.

## Explicit target idempotency and bounded replay

Status: CLI, evidence schema, and conservative capability gate implemented.
Automatic replay remains unavailable until a backend proves non-overlapping
attempt fencing across every ambiguous boundary.

Cloudmake treats every project target as potentially effectful and submits it at
most once by default. It now accepts an explicit per-invocation declaration
that the selected target is idempotent, while keeping the separate bounded
replay request unavailable until a backend proves the necessary fencing. It
does not infer idempotency from a target name, Make syntax, project file, or a
previous successful run.

The approved CLI is:

```text
cloudmake --idempotent --replay-for=DURATION TARGET [NAME=value ...]
```

`--idempotent` is the operator's semantic assertion about only this requested
target invocation. `--replay-for` selects a bounded delivery policy and is
invalid without `--idempotent`. Cloudmake also applies a small fixed attempt
ceiling so the policy is bounded by both time and count. `--retry-for` retains
its existing, separate meaning: retry classified provider allocation capacity
before target submission.

The implementation must keep these concepts separate:

1. target semantic: unknown/effectful or operator-declared idempotent for this invocation;
2. delivery policy: at-most-once or explicitly bounded replay;
3. observed submission state: `not_submitted`, `submitted`, or `ambiguous`; and
4. derived decision: whether replay is safe in the observed backend state.

Acceptance requirements:

1. Existing invocations retain at-most-once behavior.
2. The declaration applies only to the requested project target; it is not a
   reserved Make target, project-file declaration, or persistent assumption
   about similarly named work.
3. Ordinary nonzero Make results are never replayed.
4. Authentication, configuration, source, preparation, and collection errors
   are not reclassified as target retries.
5. A backend must prevent or tolerate overlap with an ambiguously running prior
   attempt before replaying.
6. Retry count and time are bounded, cancellation is immediate, and allocation
   retry remains a separate policy.
7. One provenance record contains the declaration, delivery policy, every
   submission attempt, observed outcome, and final derived replay-safety state.
8. Fake-provider tests cover pre-submission failure, confirmed target failure,
   ambiguity with safe serialization, ambiguity without safe serialization,
   deadline expiry, and interruption.

Current backends reject `--replay-for` before provider contact. This exposes the
approved contract without claiming a capability the transports cannot yet
prove. `target_submission=ambiguous` therefore continues to mean that Cloudmake
will not replay the target automatically.

## Collection namespace migration

Status: implemented in the universal candidate; branch-specific adoption and
release migration remain open.

New development releases use `.cloudmake/artifacts/` as the canonical local
destination of `--collect`. Cloudmake owns the root `.cloudmake/` namespace and
excludes it from synchronized project source. It must not delete, move,
overwrite, symlink, or dual-write the former project-root `artifacts/`
directory; that name returns to ordinary project ownership.

Published tags remain immutable. The UofT teaching line stays pinned to v1.0.1
until a deliberate course migration window. Before upgrading, each course must
add `.cloudmake/artifacts/` to both `.gitignore` and `.cloudmakeignore` while
retaining its legacy `artifacts/` exclusion. This protects privacy when rolling
back to v1.0.1, which does not automatically exclude `.cloudmake/`.

Acceptance requirements:

1. Collection transactionally replaces only `.cloudmake/artifacts/` and
   preserves the previous collected result after interruption or unsafe input.
2. A pre-existing project-root `artifacts/` remains byte-for-byte untouched and
   participates in ordinary source selection unless the project excludes it.
3. `.cloudmake/` is automatically excluded from source synchronization and
   source fingerprints; `.artifacts/` has no special meaning.
4. CLI output, provenance, documentation, tests, examples, and acceptance
   scripts consistently name the new destination.
5. Release notes call out both the destination change and the newly reserved
   `.cloudmake/` namespace. No release describes this as a transparent patch.
6. UofT migration separately updates course documentation, ignore rules,
   version/commit/archive pins, retained evidence, and rollback instructions
   before advancing the `uoft` branch.

## Managed-checkpoint model consolidation

Status: design established and largely implemented; consolidation audit required
before the next release is declared complete.

The Day 2 tutorial review narrowed the persistence story to the problem
Cloudmake actually solves on ephemeral compute: recovering useful project build
state from a separate durable checkpoint repository. Native durable filesystems
remain valid backend behavior behind the same `--persist` surface, but they are
not the motivating checkpoint mechanism and perform no checkpoint transfer.

### Design decisions recorded by the tutorial review

1. **A checkpoint is disposable acceleration state.** Selected local source and
   the project Makefile remain authoritative. Losing or purging every checkpoint
   may increase reconstruction time but must not change project meaning or
   correctness.
2. **The execution workspace and checkpoint repository are different places.**
   Make runs on the execution machine's fast writable filesystem. The durable
   repository stores incremental snapshots and is accessed only at restore and
   publication boundaries.
3. **Nearby cloud storage is a backend mechanism, not a project contract.** It
   avoids repeatedly moving a large build tree through the laptop, but its
   authorization, quota, retention, performance, and price remain provider
   properties.
4. **Replacement recovery has one ordering.** Restore the checkpoint head,
   reconcile authoritative current source over it, run the requested Make target
   once, then publish only after confirmed success.
5. **Publication is transactional.** A snapshot is immutable, and the checkpoint
   head advances last only after the candidate is complete and verified. Target
   failure, ambiguous completion, interruption, corruption, or a concurrent
   writer leaves the previous head usable.
6. **The automatic safe point is a completed Make target.** Cloudmake does not
   infer application consistency inside a running target. Mid-target recovery
   requires a future explicit project protocol and cannot be inferred from target
   names or file activity.
7. **Only managed-workspace contents are checkpointable.** Cloudmake does not
   capture running processes, kernel or driver state, or installations written
   only to machine-owned paths. Reusable project build state must live inside the
   execution workspace.
8. **The common CLI remains mechanism-neutral.** `--persist` selects the available
   backend behavior: managed checkpointing for an ephemeral workspace or a
   no-transfer native durability path. Backend-specific storage operations do not
   become project Make targets.

The consolidation revision must verify that CLI help, banners, provenance,
backend descriptors, and documentation consistently distinguish
`managed checkpoint` from `native durability` while preserving the single
high-level selection. It must not reintroduce caches, OCI images, collected
artifacts, or suspended VMs as synonyms for a workspace checkpoint.

Acceptance requirements:

1. Persistence remains opt-in and stateless execution remains behaviorally
   unchanged when it is not selected.
2. Replacement-VM tests prove restore, source reconciliation, target dispatch,
   snapshot verification, and head publication in that order.
3. Failure and ambiguous-submission tests prove that no new head is published.
4. Source deletion and conflict tests preserve remote-generated descendants while
   ensuring current source wins wherever it owns a path.
5. Purge and missing/corrupt-checkpoint tests preserve clean reconstruction as a
   valid outcome.
6. Native-durability backends perform no checkpoint transfer and accurately
   report provider deletion and retention as outside Cloudmake's guarantee.
7. Workspace list, attach, show, and purge operations apply only to
   Cloudmake-managed checkpoint repositories.
8. Provenance records restore and publication outcomes without storing provider
   credentials or the checkpoint encryption key.

## Workstation-contract qualification

Status: open; required before the next release is declared complete.

The Day 3 tutorial and 2.4 contract separate the user-supplied workstation
contract from backend capabilities and launcher authority. Complete the
implementation contract so dynamic qualification returns the selected
realization and concise compatibility evidence instead of using “qualified” as
an overloaded boolean. Cloudmake must preserve OCI Runtime, CDI, and Dev
Container vocabulary rather than inventing a parallel execution profile.

### Design changes recorded by the tutorial review

1. **The workstation contract is the only workload contract.** It comprises OCI
   Image/Distribution/Runtime behavior, CDI device requests, and Dev Container
   workstation behavior. Cloudmake may normalize syntax internally for matching
   and diagnostics, but it must retain attribution to those standards.
2. **Backend capabilities describe supply, not another workload model.** They
   declare candidate native realizations and bounded adapters and provide the
   policy and live facts needed to judge the contract.
3. **Retire the proposed four-field execution profile.** `boundary`,
   `authority`, `resources`, and `network` must not become a new user-facing or
   provenance contract. Workload requirements already belong to OCI Runtime,
   CDI, and Dev Container semantics. Backend isolation, launcher authority,
   resources, devices, and connectivity remain capability evidence where
   relevant.
4. **Qualification is a decision, not an environment description.** Its result
   is one complete selected realization plus supporting evidence, or a rejection
   attributed to an unsatisfied workstation-contract requirement.
5. **Adapters close only the realization-mechanism gap.** An adapter may make a
   contract executable without provider-native Dev Container machinery, but it
   may not relax the contract, platform isolation, or provider policy. If it
   cannot preserve the complete requested behavior, qualification rejects before
   Make.
6. **Legacy backend vocabulary remains compatible but subordinate.** The
   transport capability named `environment-profile` continues to mean that a
   backend can collect machine evidence. It is not renamed into, or exposed as,
   a workstation contract.

The consolidation revision must remove any planned CLI, status, provenance, or
backend API that emits the discarded four-field profile. No production schema
currently implements that proposal, so this is a design correction rather than
a compatibility migration. Existing backend network declarations and machine
evidence remain useful inputs to qualification.

Acceptance requirements:

1. Backend descriptors declare candidate realizations and launcher authority
   without confusing that declaration with live qualification.
2. Qualification combines declared provider policy with live probes of the
   chosen runtime and every contract requirement that needs live proof,
   including resources, devices, privilege, and safely testable network
   behavior.
3. The analyzer emits the workstation contract; qualification returns a
   realization decision and evidence. Requested and observed state are not
   mixed in one object.
4. `conditional`, `inherited`, and `unknown` remain explicit where proof is
   unavailable; a configuration requiring such a property fails unless the
   backend can provide it.
5. Backend policy rejects workload authority it does not permit; no fallback
   silently gains broader authority.
6. Candidate order remains backend-defined and observable.
7. Routine target output remains compact. Explicit environment inspection and
   provenance present the selected realization and relevant evidence and may
   additionally record launcher authority without exposing credentials or host
   secrets.
8. Diagnostics name the unsatisfied OCI, CDI, or Dev Container requirement;
   they do not reject against a Cloudmake-specific profile field.
9. Tests cover native realization, successful bounded adaptation, fundamental
   incompatibility, a declared-but-unready realization, a permitted fallback,
   forbidden escalation, and a provider-mediated realization.
