# Execution environments and OCI roadmap

This document freezes the boundary between Cloudmake 2.0 persistent workspaces
and the planned Cloudmake 2.1 OCI/CDI execution surface. It is normative for
those releases; research experiments do not expand the supported interface.

## Orthogonal model

A Cloudmake execution is the composition of four independent choices:

| Axis | Cloudmake 2.0 | Planned extension |
| --- | --- | --- |
| Compute backend | local, Colab, Kaggle, SSH, Codespaces, Lightning | additional provider adapters |
| Runner | native Make | OCI/CDI Make |
| Persistence | off or persistent workspace | additional durable-store adapters |
| Source | synchronized local tree | Git/registry-backed source acquisition |

The axes must remain independent. In particular:

- enabling persistence does not select an application format or runner;
- selecting an OCI image does not imply that its immutable layers belong in a
  mutable workspace checkpoint;
- a project Make target remains the unit of dispatch under either runner; and
- source acquisition does not become container-image construction.

This model is the path from short-lived cloud compute to a remote-workstation
experience: replaceable compute, reproducible tools, durable mutable work, and
portable source are composed without pretending they are one kind of state.

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
- `/dev/fuse`, `/dev/kvm`, and NVIDIA visibility.

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

The next capability step adds exactly one managed non-native runner: OCI with
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

Cloudmake therefore has three validation layers:

1. inspect and pin the image manifest and configuration by digest;
2. compare declared OCI/CDI requirements with observed VM facts; and
3. ask the selected runtime to perform a bounded preflight before dispatching
   the project target.

A positively incompatible requirement fails before Make. Missing or ambiguous
evidence is reported honestly; Cloudmake must not claim compatibility based
only on an installed `docker`, `podman`, or other client. Once preflight passes,
Cloudmake invokes the requested project Make target exactly once inside the
image, preserving the same target and assignment syntax as native execution.

The supported product surface remains intentionally small:

```text
native Make
OCI/CDI Make
```

Nix may build an OCI image upstream; Cloudmake does not need to know. Apptainer,
SIF, Nix closures, PRoot, and other mechanisms may still appear inside ordinary
project recipes, but Cloudmake neither selects nor validates them as managed
runners. OCI must be validated as OCI; conversion to SIF is not OCI evidence.

## Image and checkpoint storage

An OCI registry is the authority for immutable image content. The image is
referenced by digest and pulled or materialized on each fresh VM. A reused VM
may use its runtime's local layer cache. Google Drive or another workspace
store remains the authority only for mutable project state.

Cloudmake must not copy registry layers into every workspace checkpoint. A
future optional image cache may reduce repeated pulls, but it is a separate,
discardable optimization whose absence cannot affect correctness. Registry and
runtime credentials remain with their official clients; they are never placed
in project source, checkpoint metadata, or provenance.

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
2. **2.1 OCI acceptance:** Cloudmake directly executes the pinned
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
