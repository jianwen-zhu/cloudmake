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
| `local` | supported | Podman, Docker, nerdctl, then PRoot fallback | passed to native runtime; rejected by PRoot |
| `host-ssh`, `codespaces-ssh`, `lightning-studio-ssh`, `colab-ssh` | supported | same ordered remote selection | passed to native runtime; rejected by PRoot |
| `colab-notebook` | supported for trusted Linux images | `skopeo` + `umoci` materialization and one provider-qualified `crun` adapter | NVIDIA devices and driver mounts through generated CDI |
| `kaggle-notebook` | unsupported | none | rejected before provider contact |

These choices are backend declarations rather than launcher special cases:

```make
BACKEND_OCI_RUNTIMES := podman docker nerdctl proot  # local and SSH hosts
BACKEND_OCI_RUNTIMES := crun                         # Colab notebook
BACKEND_OCI_RUNTIMES := none                         # Kaggle notebook
```

The list is ordered and may contain multiple dynamically qualified options.
Cloudmake first filters it against static requirements such as CDI, then probes
the selected VM. For example, if Podman is installed but its machine or daemon
is unavailable, Docker may qualify next. This readiness fallback occurs before
image preparation and target submission; Cloudmake never switches runtimes and
replays a project target after submission.

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
provide configured emulation. PRoot cannot safely inject CDI devices, so
Cloudmake rejects that combination rather than silently running on the CPU.
The Colab adapter supports the qualified NVIDIA CDI path and rejects missing or
ambiguous device evidence before Make.

The supported product surface remains intentionally small:

```text
native Make
OCI/CDI Make
```

Nix may build an OCI image upstream; Cloudmake does not need to know. Apptainer,
SIF, Nix closures, and other mechanisms may still appear inside ordinary
project recipes, but Cloudmake neither selects nor validates them as managed
runners. OCI must be validated as OCI; conversion to SIF is not OCI evidence.

## Image and checkpoint storage

An OCI registry is the authority for immutable image content. The image is
referenced by digest and pulled or materialized on each fresh VM. A reused VM
may use its runtime's content-addressed local image cache. Google Drive or another workspace
store remains the authority only for mutable project state.

Cloudmake does not copy registry layers into workspace checkpoints. The runtime
cache is separate, discardable VM state whose absence cannot affect
correctness. Registry and runtime credentials remain with their official
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
