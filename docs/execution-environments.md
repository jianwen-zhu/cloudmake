# Execution environments and OCI runner

This document defines the boundary between Cloudmake 2.0 persistent workspaces
and the Cloudmake 2.1 OCI/CDI execution surface. It is normative for those
releases; research experiments do not expand the supported interface.

## Backend roles and orthogonal choices

Cloudmake treats a backend as a composition point for three service adapters:

| Backend role | Responsibility | Example |
| --- | --- | --- |
| Compute adapter | Allocate, identify, start/stop, and execute on a compute platform | Colab session API, Kaggle batch API, SSH host |
| Persistence adapter | Preserve or attach mutable project state across the supported lifecycle | encrypted Drive checkpoint, provider-persistent volume, local tree |
| Bundle-runtime adapter | Qualify and execute a reproducible application tool bundle | Podman/Docker/nerdctl, PRoot fallback, Colab `crun` profile |

These roles are independent capabilities, not a requirement that every backend
implement all three. A Cloudmake execution then composes four choices:

| Axis | Native/default surface | Managed extension |
| --- | --- | --- |
| Compute backend | local, Colab, Kaggle, SSH, Codespaces, Lightning | additional provider adapters |
| Runner | native Make | OCI/CDI Make (2.1) |
| Persistence | off or persistent workspace | additional durable-store adapters |
| Source | synchronized local tree | Git/registry-backed source acquisition |

The axes must remain independent. In particular:

- enabling persistence does not select an application format or runner;
- selecting an OCI image does not imply that its immutable layers belong in a
  mutable workspace checkpoint;
- a project Make target remains the unit of dispatch under either runner; and
- source acquisition does not become container-image construction.

## Least-privileged computational execution

Cloudmake's OCI positioning is **least-privileged OCI execution for automated
computational workloads**, not general-purpose container hosting. A normal
runner needs an immutable userspace, the project workspace, temporary storage,
and explicitly selected devices. It does not need privileged mode, arbitrary
host mounts, host credential inheritance, service management, published ports,
or nested containers.

This is both a security and portability contract:

- users should not expose credentials or unrelated host state to the selected
  image;
- providers should not have to grant capabilities, writable kernel control
  surfaces, or devices unrelated to the computation; and
- backends that cannot support an unrestricted Docker host may still qualify a
  smaller, actively validated OCI execution profile.

Every additional mount, capability, device, namespace exception, credential,
or host integration must be justified by the backend, an explicit CDI request,
or the core Make execution contract. Convenience alone is insufficient.
Cloudmake records public Internet inbound and workload Internet outbound as two
separate backend properties. Provider command submission and authenticated
runtime proxies are control transports, not public inbound endpoints. Local and
user-managed hosts inherit their existing policy; managed providers declare
qualified, absent, or conditional reachability. Cloudmake does not become a
network configurator, firewall manager, or port-publishing service. A backend
whose outbound access is conditional must positively probe it before
Cloudmake-managed network preparation when the invocation requests that
surface. Native Make targets remain opaque and retain responsibility for their
own undeclared network dependencies.

Least privilege concerns workload authority; it is not synonymous with strong
container isolation. If a managed backend must share the VM kernel, namespaces,
or host interfaces, its qualification must say so and may restrict execution to
trusted images. The outer provider VM remains the ultimate security boundary.

This model is the path from short-lived cloud compute to a remote-workstation
experience: replaceable compute, reproducible professional tool bundles,
durable mutable work, and portable source are composed without pretending they
are one kind of state.

## Cloudmake 2.0: format-neutral workspaces

Cloudmake 2.0 manages only the native Make runner and optional workspace
persistence. It checkpoints project-generated filesystem state without
interpreting that state as a Nix closure, OCI image, SIF, compiler installation,
or application database.

Projects may use any of those mechanisms in their own recipes. Their ordinary
files can be checkpointed when they remain within the managed workspace, but
that does not make the mechanism a Cloudmake feature or compatibility promise.
There is deliberately no `--nix`, `--sif`, or generic bundle selector.

Run this to observe the selected machine:

```sh
cloudmake --environment
```

For `local`, the command observes the local machine. For `colab-notebook`, it
starts or reuses the selected session and probes that VM without synchronizing
or executing the project. The compact output and retained JSON profile record:

- OS, kernel, architecture, libc, CPU count, memory, and workspace disk;
- effective UID and selected effective Linux capabilities;
- workspace filesystem type plus executable-file, symlink, hard-link, and
  extended-attribute behavior;
- active user-namespace and private bind-mount probes;
- cgroup generation and writability;
- `/dev/fuse`, `/dev/kvm`, and NVIDIA visibility;
- installed OCI clients and fallback tools;
- installed OCI materialization and execution clients, reported only as
  observations pending active runner preflight; and
- CDI JSON specification names observed in standard static and dynamic
  directories (YAML files are counted but left to the runtime to validate).

Active probes are bounded child processes. Filesystem probes use and remove a
temporary directory beneath the selected workspace. Namespace and bind-mount
probes run in a child namespace and do not alter the host mount table. The
command does not install a runtime, pull an image, or declare an application
format compatible.

Every value is **observed**, not a provider guarantee. Managed VM images and
policies can change between allocations. A later runner may compare these facts
with an explicit execution contract, but must actively validate the actual VM
instead of inferring support from the presence of a client executable.

## Cloudmake 2.1: managed OCI/CDI runner

Cloudmake 2.1 adds exactly one managed non-native runner: OCI with
device requirements expressed through CDI where applicable. OCI is selected
because it provides a widely used, registry-backed, content-addressed image
format plus standardized runtime configuration. CDI adds a standard vocabulary
for injecting devices such as accelerators.

OCI and CDI do not by themselves prove that a VM can run an image:

- an OCI image describes userspace content and execution configuration;
- the OCI Runtime Specification describes the runtime contract;
- CDI describes device injection, not provider allocation or scheduling; and
- the host kernel, architecture, driver, privileges, namespaces, mounts,
  cgroups, and chosen runtime still determine whether execution is possible.

Nor does an OCI image carry a standardized list of privileges its application
requires. Image configuration supplies execution defaults; capabilities,
namespaces, security policy, and host mounts are part of the runtime
specification constructed at launch. Cloudmake constructs that specification
from its least-privileged profile and explicit CDI device requests rather than
accepting a general caller-supplied runtime spec. This prevents silent privilege
granting, but it cannot pre-classify an implicit target-specific need for root
or another unsupported facility. Such an image is outside the supported profile
and may fail only when its project target runs.

Cloudmake therefore uses three validation layers:

1. require and inspect an immutable image reference by digest;
2. record relevant observed VM and CDI facts without turning them into a
   provider guarantee; and
3. ask the selected runtime to pull/materialize the exact image and perform a
   bounded Make-and-device preflight before dispatching
   the project target.

A positively incompatible requirement fails before Make. Missing or ambiguous
evidence is reported honestly; Cloudmake must not claim compatibility based
only on an installed `docker`, `podman`, or other client. Once preflight passes,
Cloudmake invokes the requested project Make target exactly once inside the
image, preserving the same target and assignment syntax as native execution.
The image must contain `make`; Cloudmake overrides its entry point and working
directory so the command remains `make -f Makefile ... -- TARGET` in the
project mounted at `/workspace`.

Select an image once for a project, then run ordinary targets:

```sh
cloudmake --use local \
  --image registry.example/team/tools@sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
cloudmake verify
```

For a runtime-managed accelerator, add one or more standard CDI qualified
device names:

```sh
cloudmake --image registry.example/team/cuda@sha256:DIGEST \
  --device nvidia.com/gpu=all benchmark
```

`DIGEST` above is explanatory; the real CLI requires 64 lowercase hexadecimal
digits. `--native` clears the project's saved image and device selection.
`--no-devices` retains the image while clearing its saved devices. A new
`--image` never inherits devices from an older image. Runner preferences are
stored in Cloudmake's local per-project configuration; they do not modify the
project. An explicit `-b` remains a one-invocation backend override. `--start`
selects and starts compute but deliberately does not pull the image: image
preflight happens immediately before a project target, when the execution VM
is known.

### Backend and runtime profiles

| Backend | OCI execution | Runtime selection | CDI |
| --- | --- | --- | --- |
| `local` | supported | Podman, Docker, nerdctl, then PRoot fallback | native CDI or validated PRoot bind/environment translation |
| `host-ssh`, `lightning-studio-ssh`, `colab-ssh` | supported | same ordered remote selection | native CDI or validated PRoot translation |
| `codespaces-ssh` | supported | selected image becomes the provider dev container; no nested runtime | none; qualified CPU backend |
| `colab-notebook` | supported for trusted Linux images | `skopeo` + `umoci` materialization and one provider-qualified `crun` adapter | NVIDIA devices and driver mounts through generated CDI |
| `kaggle-notebook` | deprecated experimental profile for trusted Linux images | `skopeo` + `umoci` materialization and PRoot | qualified NVIDIA `all` device translated from generated CDI; fail closed when absent |

These choices are backend declarations rather than launcher special cases:

```make
BACKEND_OCI_RUNTIMES := podman docker nerdctl proot  # local and SSH hosts
BACKEND_OCI_RUNTIMES := crun                         # Colab notebook
BACKEND_OCI_RUNTIMES := proot                        # Kaggle notebook
BACKEND_OCI_NATIVE := yes                            # Codespaces dev container
BACKEND_OCI_RUNTIMES := none                         # no nested runtime there
```

The list is ordered and may contain multiple dynamically qualified options.
Cloudmake first filters it against static requirements such as CDI, then probes
the selected VM. For example, if Podman is installed but its machine or daemon
is unavailable, Docker may qualify next. This readiness fallback occurs before
image preparation and target submission; Cloudmake never switches runtimes and
replays a project target after submission.

Codespaces uses the orthogonal `oci-native=yes` contract. Its anchor supplies
SSH and synchronization; a selected digest becomes the dev-container base and
Cloudmake adds the same small transport surface. The provider rebuild is image
preparation, not target submission, and is skipped while the recorded digest
and adapter revision match. Codespaces is qualified as a CPU backend and
rejects CDI requests before rebuild. The complete boundary is documented in
[Codespaces native OCI](codespaces-native-oci.md).

Cloudmake installs `skopeo`, `umoci`, and `crun` as transient runner plumbing on
a Colab VM when needed. It does not install the project's compiler or tool
suite; those belong to the selected image. The adapter materializes the image,
runs it with no cgroup, and retains the mount namespace while sharing the host
PID and network namespaces. It binds the host `/proc` writable, `/sys`
read-only, a fresh `/tmp`, the project workspace writable, and a narrow standard
device set. NVIDIA device nodes, driver libraries, and `nvidia-smi` are added
only through the generated CDI specification. The image root remains read-only.
Make runs as UID/GID 65534 with empty capability sets and `noNewPrivileges`.

Changes outside `/workspace` disappear with the invocation; the cached image
root remains immutable. This host-integrated adapter is compatibility plumbing,
not a strong sandbox. It shares the Colab VM kernel, PID namespace, network,
and host `/proc`; images used on this path must be trusted. It does not bind
host credential directories or unrelated writable host paths.

Native runtimes receive CDI qualified names through their standard device
surface. Their bounded preflight is authoritative: a missing CDI specification,
driver, runtime feature, unsupported image architecture, or `make` executable
fails before the requested target is submitted. A static host/image architecture
mismatch is recorded but is not alone a failure because a native runtime may
provide configured emulation. The PRoot adapter translates the strict CDI
mount, device-node, and environment subset it can faithfully represent and
rejects hooks, ownership overrides, and unknown edits. Colab and Kaggle generate
their NVIDIA CDI evidence from the actually attached VM and reject missing or
ambiguous devices before Make rather than silently running on CPU.

The supported product surface remains intentionally small:

```text
native Make
OCI/CDI Make
```

Nix may build an OCI image upstream; Cloudmake does not need to know. Apptainer,
SIF, Nix closures, and other mechanisms may still appear inside ordinary
project recipes, but Cloudmake neither selects nor validates them as managed
runners. OCI must be validated as OCI; conversion to SIF is not OCI evidence.

## Historical Kaggle no-reuse validation

Kaggle provided the deliberate counterpoint to Colab in Cloudmake's backend
model, but is deprecated for remote-workstation use. The implementation remains
available for compatibility and coarse batch experimentation; it does not gate
the 2.1 release. The retained evidence is documented in the
[historical backend report](historical/kaggle-notebook.md).

Colab can amortize source, image, and workspace preparation across targets in a
reused session. Kaggle assigns fresh compute to every notebook version and
therefore declares `session-reuse=no`. “Batch” and “fresh per target” are
descriptions of that single property, not independent capabilities. Whether
Kaggle releases the underlying VM is provider implementation behavior and does
not require a Cloudmake `release` property.

Kaggle composes two independent adapters without changing that reuse property:

1. a persistence adapter that alternates private notebook-output slots, restores
   the locally recorded last-good slot through a provider-side `kernel_source`,
   and publishes its successor without exposing Kaggle credentials; and
2. a least-privileged PRoot OCI adapter that materializes a Linux image without
   a daemon or privileged namespaces and translates its supported CDI subset.

This preserves incremental Make *state*, not cheap incremental
dispatch. Every target still pays for a fresh VM, source staging,
workspace restore, OCI materialization when uncached, and successful checkpoint
publication. Cloudmake identifies those costs as properties of the backend
rather than compensating with implicit target aggregation or a scheduler. Live
ECE467 evaluation measured a roughly 14.5 GB restore/materialize/publish cycle
on each target, which made this backend unsuitable for the intended workstation
loop.

The persistence gate proves provider-side restore and publication without a
laptop round trip for the checkpoint payload, deterministic version selection,
private ownership, receipt-validated checkpoint advancement, and absence of
Kaggle credentials from generated notebooks, output, provenance, and
checkpoints. Only successful Make invocations publish a new checkpoint; target
and infrastructure failures leave the last-good head unchanged. Kaggle storage
quotas and retention are provider limits, not new Cloudmake ceilings.

## Image and checkpoint storage

An OCI registry is the authority for immutable image content. The image is
referenced by digest and pulled or materialized on each fresh VM. A reused VM
may use its runtime's content-addressed local image cache. Google Drive or another workspace
store remains the authority only for mutable project state.

Colab and ordinary host runtime caches remain separate and discardable. Kaggle
places downloaded runner packages and its materialized OCI cache inside the
private workspace checkpoint because `session-reuse=no` would otherwise force a
large pull every target. The registry remains authoritative, and deletion of
that cache affects cost rather than correctness. Registry and runtime credentials remain with their official
clients; they are never placed in project source, checkpoint metadata, or
provenance. Cloudmake passes no host environment variables into native OCI
containers. Its PRoot and Colab `crun` paths start project Make with a clean
environment populated only from validated OCI image configuration plus safe
`PATH`/`HOME` defaults. Image references, observed platform facts,
selected CDI names, runtime name, and outcome are non-secret provenance.

## Filesystem safety

Cloudmake separates paths by ownership rather than format:

- synchronized source paths are local-source-owned;
- other paths created beneath the remote project tree are project-generated;
- Cloudmake control records live beside its internal source directory.

Uploaded source remains strict: traversal, absolute or escaping links, special
files, and paths outside the selected project are rejected. Generated state may
contain relative, absolute, or escaping symbolic-link objects because restic
stores links without following them and Cloudmake traverses with link following
disabled. Devices, FIFOs, sockets, and other special files remain rejected;
artifact collection cannot follow a resolved path outside the project.

These are checkpoint safety rules, not application-format recognition.

## ORFS validation ladder

OpenROAD Flow Scripts (ORFS) is the final application verdict, not the first
development fixture. It is valuable because it combines a large tool suite,
long-running stage targets, sizeable generated state, and an existing OCI
workflow.

The releases validate ORFS in two independent steps:

1. **2.0 checkpoint acceptance:** an ordinary project-owned Make workflow runs
   native targets, publishes a successful stage boundary, destroys the Colab
   VM, restores the workspace, and continues without rebuilding durable state.
   Cloudmake does not interpret target names or `.odb` files.
2. **2.1 OCI acceptance:** Cloudmake directly executes a pinned
   `openroad/orfs` OCI digest through its managed OCI runner, first without
   persistence and then composed with the already accepted 2.0 workspace.

ORFS stage targets such as `floorplan`, `place`, `cts`, `route`, and `finish`
provide natural project-owned checkpoint boundaries. A checkpoint is published
only after a target succeeds. Cloudmake never guesses whether an interrupted
EDA stage left a valid database and never automatically reruns an ambiguously
completed target.

For headless cloud execution, the OCI profile should mount only the project
workspace and required devices. It should not inherit ORFS's interactive X11 or
host-network conveniences unless the project explicitly requests them.

## Deferred work

The following are outside 2.0 and 2.1:

- a generic application-bundle framework;
- managed SIF or Nix runners;
- automatic conversion between distribution formats;
- a persistent queue or scheduler;
- automatic recovery inside an arbitrary in-flight Make target; and
- Git/GitHub source acquisition.

These boundaries keep the checkpoint release independently useful and make the
OCI release testable without conflating immutable tools with mutable work.
