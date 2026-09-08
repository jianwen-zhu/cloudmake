# Backend contract

Cloudmake backends adapt local execution and different provider lifecycles and
transports to one execution model: invoke an ordinary Make target against the
selected working tree and optionally retrieve output. Remote backends synchronize
the local tree first. This document is for cloudmake backend
authors and maintainers. Project developers should instead read the
[project contract](project-contract.md).

## Project boundary

Every backend must implement the separate [project contract](project-contract.md)
without adding provider-specific project requirements. In particular, a
backend must preserve project-relative paths, dispatch the exact requested Make
target without injecting Make variables, and avoid requiring a provider notebook
or provider-specific Makefile in the project.

Trailing project `NAME=value` arguments must remain opaque to the host engine.
A backend reads its own settings from explicit launcher options or the host
environment, never by interpreting the project's assignment namespace.

Backend lifecycle operations are selected through launcher options such as
`--status` and `--fetch`. A positional name with the same spelling remains a
project target. The target-agnostic `--collect DIR TARGET` operation must validate
`DIR` as project-relative, invoke the exact requested target, archive that
existing directory after success, and transactionally replace the local
`artifacts/` directory.

## Names and transports

User aliases are short; canonical names identify transport explicitly:

| User alias | Canonical backend | Transport | Persistence mode |
| --- | --- | --- | --- |
| `local` | `local` | Direct project Make invocation | `native` |
| `colab` | `colab-notebook` | Native Colab contents and kernel APIs | `checkpoint` |
| `kaggle` | `kaggle-notebook` | Private Kaggle notebook version | `unsupported` |
| `codespaces` | `codespaces-ssh` | SSH and rsync | `native` |
| `colab-ssh` | `colab-ssh` | SSH and rsync | `unsupported` |
| `ssh` | `host-ssh` | User-managed SSH and rsync | `native` |
| `lightning` | `lightning-studio-ssh` | SSH and rsync | `native` |

An alias must not silently change transport. In particular, `colab` always
means native notebook access and never falls back to SSH.

## Backend descriptor

Each backend declares:

- the supported backend API version;
- a canonical backend name;
- a lifecycle: `local`, `session`, or `batch`;
- an ordered set of capabilities; and
- a resource identifier suitable for local serialization.

The shared core validates the descriptor before running an operational target.
Inspect the resolved descriptor with:

```sh
make BACKEND=colab-notebook backend-info
```

Capabilities describe real behavior rather than provider branding. Examples
include synchronization, execution, artifact retrieval, status, opening a web
interface, stopping reusable compute, and an interactive shell. A backend must
not advertise a shell merely because its provider has a browser terminal.

`environment-profile` is separate from these Cloudmake backend capabilities.
It means the backend can observe the selected execution VM and report the
machine, privilege, filesystem, isolation, device, and accelerator evidence
defined in [Execution environments and OCI runner](execution-environments.md).
It does not imply support for a particular application format or runner.
Observed properties are not provider guarantees and must not be cached as if
they were promises for a replacement VM.

`oci-runner` is an execution capability, not a persistence mode. A supporting
transport must place the Cloudmake OCI runner beside its own control files,
select an available implementation on the execution VM, perform image/Make/CDI
preflight before target submission, and retrieve the terminal runner receipt.
The requested target may execute at most once. Native execution must remain
byte-for-byte compatible when `CLOUDMAKE_RUNNER=native`; adding OCI support may
not impose an image, runtime dependency, or changed Make command on existing
users. A backend that cannot provide the OCI runner rejects the selection before
provider contact.

All implementations present the project at `/workspace`, use only the OCI
image environment plus explicit Cloudmake command arguments, and distinguish a
runner-infrastructure receipt from the requested Make target's exit status. A
restricted adapter without a native OCI runtime must additionally validate its
mount operations on the actual VM, disable setuid/file-capability elevation,
drop the target to a non-root identity, and document any shared host namespaces.
Observed privilege or an installed command makes such an adapter only a
candidate; it is not a compatibility guarantee.

Every backend must also declare an ordered `BACKEND_OCI_RUNTIMES` list. Use
`none` when OCI is unsupported. The supported runtime vocabulary is `podman`,
`docker`, `nerdctl`, `proot`, and `chroot`. For example:

```make
# A host whose installed execution surface must be discovered dynamically.
BACKEND_OCI_RUNTIMES := podman docker nerdctl proot

# A managed notebook with one provider-qualified adapter.
BACKEND_OCI_RUNTIMES := chroot
```

The declaration describes mechanisms the backend permits, not commands proven
to work on every instance. Cloudmake rejects selections that no declared option
can satisfy, then probes the actual VM in declaration order. An installed but
unready native runtime is skipped so another declared option can qualify. The
image-specific preflight remains the final authority and never causes target
replay.

`checkpoint-persistence` means Cloudmake transfers a managed workspace through
an independent durable checkpoint store. `native-persistence` means the
backend's ordinary project workspace already survives its supported stop/start
lifecycle; selecting persistence adds no transfer or checkpoint credential.
A backend advertising neither capability must reject enabled persistence before
provider contact. It must never silently accept the option merely because some
local source archive or provider output happens to be cached.

These modes describe mechanism, not unlimited retention. A native workspace
still disappears if its provider resource or storage is deleted. The launcher
keeps persistence disabled by default for backward compatibility and passes
`CLOUDMAKE_CHECKPOINT=1` to the internal engine only for the managed checkpoint
mode. This variable never enters the project Make assignment namespace.

## Lifecycle semantics

A `local` backend has no compute lifecycle or synchronization boundary. Public
project-target execution invokes the project Makefile directly; lifecycle and
synchronization operations report explicit no-op or readiness semantics. It is
the reference behavior that remote backends must preserve.

A `session` backend may start or reuse a named VM. It must reconcile cached
identity with live provider state before use and expose a meaningful `stop`
operation. For an externally managed host such as `host-ssh`, `start` means
validate the existing execution surface and `stop` must explicitly preserve the
machine rather than claiming lifecycle authority Cloudmake does not have.

Native Colab derives its default resource identifier from stable local project
identity. An explicit `COLAB_SESSION` remains exact, and existing local state
for the v0.9 `cuda-build` default selects that legacy name. This prevents two
unrelated projects from silently sharing a mutable session while retaining an
intentional shared-session escape hatch guarded by normal ownership checks.
`COLAB_SESSION=NAME cloudmake --use colab` persists a deliberate per-project
replacement; a one-off environment override is not persisted.

A `batch` backend submits a fresh job for each operational target. `start` may
validate readiness, but it must not pretend to create a reusable VM. `stop` may
be a documented no-op when the provider ends jobs automatically.

Capacity retry is an opt-in backend allocation capability, not a wrapper around
an engine operation. A backend supporting `--retry-for` must positively classify
its own provider's temporary-capacity response, bound its wait, and stop retrying
before readiness, transfer, or project execution begins. Backends without such a
classifier reject the option. A transport must never infer retryability from an
arbitrary nonzero command or HTTP status alone.

Readiness polling is a separate pre-execution policy. It may repeat only a
non-mutating remote prerequisite probe and must have a deadline plus a bounded
per-probe timeout. The transport must record whether allocation occurred in the
current invocation and whether target submission is `not_submitted`,
`submitted`, or `ambiguous`. Once submission may have happened, neither
readiness nor capacity policy may replay the project target.

The engine's common lifecycle operations are `start`, `sync`, `status`, `fetch`,
`open`, `shell`, and `stop`; the launcher exposes them as long options. A
positional name with the same spelling remains a project target. Unsupported
operation options fail clearly rather than changing meaning per backend.

## Internal engine dispatch

The `cloudmake` launcher is the only supported project-facing command surface.
The tool's Make engine is an internal backend-maintenance interface. It exposes
provider lifecycle operations and one generic `dispatch` entry point; the
launcher supplies the encoded project target to that entry point.

Transports must not add convenience rules for project-like names such as
`build`, `test`, or `run`. Those names have no Cloudmake meaning and may be used
only when they are supplied by the selected project's Makefile. Maintainer tests
that exercise the engine directly must also enter project execution through
`dispatch`, so the internal test surface cannot accidentally reintroduce a
predefined project-target contract. `Makefile.build` is only Cloudmake's bundled
sample project and does not define the public interface.

## Transport responsibilities

Every remote transport must:

1. gate operations on host prerequisites and a read-only provider probe;
2. use the common source scanner, manifest, exclusions, and size limits;
3. verify project ownership before replacing source;
4. serialize mutations for the selected resource;
5. verify remote execution prerequisites when the environment becomes
   reachable;
6. invoke the selected target through plain Make;
7. retrieve artifacts with safe transactional extraction; and
8. report both provider detail and a normalized cloudmake status.

Reusable transports must also distinguish synchronized source paths from
project-generated paths. Local source additions and modifications win, and
previously synchronized paths deleted locally are removed; a broad mirror
deletion must not erase generated workspace state. The cross-session extension
of this rule is specified in [Stateful workspaces](stateful-workspaces.md).

Before target submission, a session transport may retry only non-mutating
readiness probes and must bound the wait by a deadline. It may automatically
release a never-ready resource only when the current invocation has positive
evidence that it created that resource. A pre-existing unreachable resource
must not be stopped, recreated, or adopted automatically.

Likewise, transport failure is not evidence that a remote control file is
absent. Fresh/reset recovery requires a successful remote probe that positively
reports absence. If the probe says an owner or fingerprint exists but its
contents cannot be downloaded, synchronization must stop as ambiguous.

Once a target request has crossed the execution boundary, a connection failure
is ambiguous. The transport must not replay the target. Failure state records
the phase, normalized provider state, whether the invocation created the
resource, submission certainty (`not_submitted`, `submitted`, or `ambiguous`),
and whether retry is safe.

The local transport is the deliberate exception to remote synchronization,
ownership, locking, and retrieval responsibilities: it operates on the source of
truth itself. It must still preserve exact Make dispatch and apply the same safe,
transactional `artifacts/` materialization when `--collect` is requested.

Notebook transports package the selected source and execute provider control
cells. The generated notebook and control code belong to cloudmake rather than
the project. A reusable notebook session can skip upload when the manifest is
unchanged; a batch provider may reuse its local archive but still submits a new
job.

A reusable notebook resource name is not a runtime-instance identity. The
transport must check its remote owner and synchronization control records on
every invocation. Missing control state forces a full source upload and a
reported fresh/reset transition; a foreign owner remains a hard refusal unless
the operator explicitly adopts it.

SSH transports synchronize incrementally with rsync and invoke Make over the
same SSH execution surface. Provider backends supply connection discovery and
lifecycle behavior. The transport must check ownership before applying its
manifest-derived source deletion plan, and synchronize the uploaded project
independently of any anchor repository checked out by the provider.

## State boundary

Generated preferences, fingerprints, notebooks, archives, locks, SSH
configuration, and provider output are tool state. The launcher stores
them in user configuration, state, and cache directories keyed by the local
project identity. They do not belong in either the cloudmake repository or the
actual project repository.

Downloaded project output is different: cloudmake creates and owns the local
project `artifacts/` directory as the materialized result of `--collect`.

Configuration precedence is:

```text
command line
  > environment variables
  > per-project local preferences
  > optional shared project configuration
  > global user preferences
  > backend defaults
```

Provider authentication stays with the provider's own client. A backend should
reference credentials or SSH identities when needed, never copy them into
project state or a source archive.

## Adding a remote provider backend

A new remote provider backend should first choose its honest lifecycle and
transport. Reuse a shared transport when its synchronization and execution
semantics match; add a new transport only when the provider surface genuinely
differs. The built-in local backend is the reference adapter described above,
not a template for provider lifecycle code.

The implementation is complete when it has:

1. a canonical, transport-explicit name and optional human-friendly alias;
2. a valid descriptor and capability set;
3. host prerequisite and read-only authentication checks;
4. live status reconciliation;
5. source ownership, locking, transfer, and remote prerequisite handling;
6. target execution and safe artifact retrieval;
7. normalized status mappings; and
8. offline fake-provider tests for successful and failed operations, including
   proof that it does not cross architecture boundaries such as cloning the
   user's project or using SSH from a native-notebook backend.

See [Resilience and recovery](resilience.md) for the required failure behavior
and [Security model](security.md) for trust boundaries.
