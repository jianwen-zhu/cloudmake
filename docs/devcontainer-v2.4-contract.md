# Cloudmake 2.4 Dev Container contract

Status: accepted design for the Cloudmake 2.4 development line.

Implementation status: capability analysis and backend declarations are active.
The existing restricted OCI adapter remains the portable baseline. The local
backend additionally qualifies the reference Dev Container CLI over Docker for
the bounded richer field set documented in `devcontainers.md`; other backends
fail early when that richer set is requested.

Cloudmake accepts the standard `devcontainer.json` format as a workstation
configuration. It does not claim that every backend implements every part of the
Dev Container specification. Instead, Cloudmake analyzes the behavior required
by the selected configuration, compares it with the selected backend's declared
and observed capabilities, and either realizes the configuration faithfully or
rejects it before provider allocation or target submission.

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

1. **Portable behavior** has the same meaning across all qualified backends.
   The 2.3 portable core remains the baseline: image, literal environment,
   basic host requirements, bounded loopback forwarding, `/workspace`, strict
   security options, and explicit CDI device names.
2. **Advisory metadata** has no process or resource effect and may be retained
   or ignored explicitly. Examples are `$schema`, `name`, and editor-specific
   `customizations`. The accepted advisory list is closed and documented;
   unknown fields are not automatically advisory.
3. **Capability-requiring behavior** is accepted only when the chosen backend
   can preserve it. This includes image builds, Compose services, Features,
   lifecycle commands, user selection, mounts, port behavior, secrets,
   additional capabilities, privileged execution, and device integration.

The analyzer returns normalized portable values plus a set of required
capabilities. Backend validation happens before any action that could allocate
billable compute. An unsupported requirement produces a field-specific error
that names both the requirement and backend.

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

Static declarations are an upper bound. Dynamic preflight still verifies the
actual runtime, architecture, storage, network, driver, CDI, and resource state.
A declared capability that fails its dynamic probe is unavailable for that
workstation invocation.

The portable profile is the intersection that can be selected across supported
backends. Richer configurations remain standard Dev Containers but are portable
only across backends advertising their requirements. Documentation and
`cloudmake --backends` must not describe the richer set as universally portable.

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

## Least privilege

The least-privileged profile remains the default. A configuration requesting
additional authority does not automatically receive it because a backend could
technically provide it.

Privilege is a separate policy capability. It must be explicitly declared by
the project, allowed by the backend, and reported in preflight/provenance.
Restricted managed backends such as Colab may permanently reject privileged
fields while still supporting the portable image profile and CDI device
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
