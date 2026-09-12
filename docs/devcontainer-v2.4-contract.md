# Cloudmake 2.4 Dev Container contract

Status: accepted design for the Cloudmake 2.4 development line.

Implementation status: capability analysis and backend declarations are active.
The existing restricted OCI adapter remains the portable baseline. The local
backend additionally declares the reference Dev Container CLI over Docker for
the bounded richer field set documented in `devcontainers.md`; other backends
fail early when that richer set is requested.

Cloudmake accepts the standard `devcontainer.json` format as a workstation
configuration. It does not claim that every backend implements every part of the
Dev Container specification. Instead, Cloudmake analyzes the behavior required
by the selected configuration, compares it with the selected backend's declared
and observed capabilities, and either realizes the configuration faithfully or
rejects it before target submission. Static incompatibilities are rejected
before allocation when they can be known locally. Requirements that depend on
the assigned machine, runtime, driver, or device are qualified on the live
resource after allocation and still before Make runs.

This is capability negotiation, not best-effort translation. Cloudmake must
never silently remove a lifecycle command, mount, privilege, user selection,
device request, service, or other behavior merely to make a configuration run.

## Stable user surface

The normal interface remains:

```sh
cloudmake --devcontainer TARGET [NAME=value ...]
cloudmake TARGET [NAME=value ...]
```

The first form selects the standard project configuration and persists that
selection. Later targets reuse the same logical workstation selection. A
project may specify a project-relative configuration path with
`--devcontainer=PATH`; `--native` clears the selection.

Cloudmake adds no separate user-facing container lifecycle for routine work.
Backend allocation, image resolution, preparation, reuse, hibernation, and
reconstruction remain implementation details behind target execution.

## Configuration analysis

Every recognized field belongs to one of three classes.

1. **Portable behavior** has one defined meaning wherever a backend declares
   support for it. The 2.3 adapter vocabulary includes image, literal
   environment, basic host requirements, bounded loopback forwarding,
   `/workspace`, strict security options, and explicit CDI device names. A
   particular backend may support only a subset and must reject the rest.
2. **Advisory metadata** has no process or resource effect and may be retained
   or ignored explicitly. Examples are `$schema`, `name`, and editor-specific
   `customizations`. The accepted advisory list is closed and documented;
   unknown fields are not automatically advisory.
3. **Capability-requiring behavior** is accepted only when the chosen backend
   can preserve it. This includes image builds, Compose services, Features,
   lifecycle commands, user selection, mounts, port behavior, secrets,
   additional capabilities, privileged execution, and device integration.

The analyzer returns normalized portable values plus a set of required
capabilities. Static backend validation happens before allocation. Live
qualification may require the selected resource to exist, but it always
completes before target submission. An unsupported requirement produces a
field-specific error that names both the requirement and backend.

Unknown top-level fields remain fail-closed. A future Dev Container field may
alter process authority or lifecycle and must not acquire accidental semantics
in an older Cloudmake release.

## Backend capability contract

A backend declares Dev Container support independently from transport,
persistence, and OCI runtime support. The descriptor distinguishes the portable
core from optional standard behaviors such as:

```text
image-digest
image-tag
image-build
compose
features
lifecycle-create
lifecycle-start
user-selection
mounts
forward-ports
privilege
cdi
```

Names describe semantics, not the executable used to implement them. A native
Dev Container service, the reference Dev Container CLI over Docker, and a
Cloudmake restricted OCI adapter may satisfy different capability sets.

Static declarations are an upper bound. Dynamic qualification still verifies the
actual runtime, architecture, storage, network, driver, CDI, and resource state.
A declared capability that fails its dynamic probe is unavailable for that
workstation invocation.

Portable describes stable semantics, not universal availability. The subset
usable across a chosen set of backends is the intersection of their declared
and dynamically qualified capabilities. Richer configurations remain standard
Dev Containers but are usable only where every required behavior qualifies.
Documentation and `cloudmake --backends` must not imply otherwise.

## Image references and immutable workstation instances

Both standard tag references and digest references are valid input.

When a tag is selected, the backend resolves it through an existing
provider/runtime registry integration. Cloudmake records:

- the source reference from `devcontainer.json`;
- the resolved manifest digest;
- the target platform;
- the configuration fingerprint; and
- the logical workstation/resource identity.

Execution is pinned to that resolved digest. Subsequent Make targets reuse the
same resolution while the logical workstation instance remains valid. A
configuration change or workstation reconstruction creates a new resolution;
Cloudmake does not update a running workstation merely because a remote tag has
moved. Provenance always identifies the digest actually executed.

Digest input bypasses tag resolution but is still checked against the selected
platform and runtime. Resolution failure is an infrastructure/preparation
failure and occurs before Make. Cloudmake never retries the project target as a
consequence of image resolution or workstation reconstruction.

## Registry credentials

Cloudmake does not ingest, persist, serialize, upload, or print registry
credentials. Resolution and image acquisition invoke the selected backend's
existing registry client, credential helper, workload identity, or
provider-native service.

A backend that cannot access a private reference using its existing identity
must reject it. Cloudmake does not copy laptop Docker configuration, tokens, or
credential-helper output into a VM to make the pull succeed.

The source reference and resolved digest are non-secret provenance. Registry
credentials and authorization headers are not.

## Lifecycle and workstation state

Lifecycle commands are behavior, not metadata. A backend may accept them only
if it can preserve their standard ordering and durability:

- create-phase commands execute once for a newly constructed workstation;
- start-phase commands execute once for each corresponding workstation start;
- target execution begins only after required preparation succeeds; and
- a requested Make target executes at most once.

A receipt binds completed preparation to the configuration fingerprint, image
digest, platform, and logical workstation identity. Ambiguous preparation does
not cause an automatic replay.

Backends whose adapter launches a fresh read-only container for each target do
not satisfy persistent create-lifecycle semantics merely because `/workspace`
survives. They must reject those lifecycle fields until they provide a genuine
workstation root or an equivalent immutable derived image.

Checkpoints, native disks, stopped containers, and OCI caches reduce repeated
work; none is authoritative project state. Source plus declared configuration
and the project Makefile must remain sufficient to rebuild from scratch.

## Workstation requirements and dynamic qualification

The workstation contract expresses workload behavior through OCI Runtime, CDI,
and Dev Container semantics. Cloudmake does not replace their vocabulary with a
second execution-profile language. Process authority, namespaces, mounts,
resources, devices, and network behavior remain contract requirements.

Cloudmake separately records **launcher authority**: process-only, mediated, or
host-engine. This describes what Cloudmake must trust to start the workload. It
is backend implementation and security disclosure, not a project setting and
not part of the workstation contract.

Backends declare candidate native implementations and bounded adapters plus the
capabilities each can provide. Dynamic qualification compares the complete
workstation contract with one candidate and the live backend. It selects a
realization only when that realization preserves all requested behavior;
otherwise it rejects before target submission. The qualification result records
the selected realization and the evidence behind the decision, without turning
observed backend properties into project inputs.

A process-only PRoot realization may provide weaker isolation than a
host-engine Docker realization, and provider policy may permit outbound traffic
while denying inbound service. Candidate order therefore remains
backend-defined so a backend may prefer a reliable native engine over a weaker
user-space substitute.

Privilege must be explicitly requested by the workstation contract, allowed by
the backend, and reported in preflight/provenance. Dynamic qualification
resolves a statically declared realization against provider policy and live
evidence. It preserves `conditional`, `inherited`, or `unknown` where a safe
proof is unavailable and verifies every property required by the contract
before target submission. It does not mean that the backend is supported.

Restricted managed backends such as Colab may permanently reject privileged
fields while still supporting the portable image subset and CDI device
injection. Provider-native implementations remain bounded by provider policy.

This separation lets mainstream Dev Container configurations use capable
workstations without weakening Cloudmake's security promise on constrained
platforms.

## Compatibility and rollout

Projects without `--devcontainer` retain native Make behavior. Existing
digest-pinned 2.3 configurations retain their current execution semantics.
`--image REF@sha256:DIGEST` remains the minimal image-only shorthand.

The rollout order is:

1. configuration requirement analysis and backend declarations;
2. tag-to-digest resolution with provenance and reuse tests;
3. native/reference-runtime qualification for capable backends;
4. lifecycle receipts only on backends with durable workstation semantics; and
5. expanded public-corpus gates, including expected restricted-backend
   rejections.

No backend may advertise an optional capability before its offline adversarial
tests and retained live gate demonstrate the complete behavior.
