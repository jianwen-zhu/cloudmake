# OCI/CDI runner

Cloudmake 2.1 can execute an unchanged Make project with tools supplied by a
digest-pinned OCI image. This runner is independent of the selected backend and
of optional persistent workspaces.

Its product boundary is least-privileged OCI execution for trusted automated
computational workloads, not general-purpose container hosting. Cloudmake
provides the image userspace, a writable project workspace, temporary storage,
and explicitly requested CDI devices. It deliberately does not reproduce the
full `docker run` surface with privileged mode, arbitrary mounts, inherited
host credentials, public port publishing, services, or nested containers. A
portable Dev Container may request a bounded loopback port. Requiring a
smaller host surface improves both provider compatibility and security.

Least privilege does not by itself imply strong isolation. The selected
backend's documented kernel and namespace boundary remains authoritative.

## Daily use

Choose the backend and image once. Both selections are local to the project:

```sh
cloudmake --use ssh --host lab-gpu \
  --image registry.example/eda/tools@sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef \
  --device nvidia.com/gpu=all

# route and verify are targets supplied by this project's Makefile.
cloudmake route DESIGN=gcd
cloudmake verify
```

Use `--native` to return to direct Make execution, or `--no-devices` to retain
the image without requesting a device. The image selection is not a Make
assignment and Cloudmake does not add project targets.

Every image must be an immutable `REF@sha256:DIGEST` reference and contain a
working `make`. Cloudmake mounts the project at `/workspace`, overrides the
image entry point, preserves user-supplied `NAME=value` arguments, and invokes
the requested target at most once.

An OCI image configuration is not an application-requirement manifest. The
standard records defaults such as user, environment, entry point, command,
working directory, ports, and volumes; it does not declare that an application
requires privileged mode, Linux capabilities, host namespaces, or arbitrary
mounts. Those fields belong to the OCI runtime specification assembled when a
container is created. Cloudmake owns that launch specification and deliberately
constructs a narrower `least-privileged-compute-v1` policy instead of accepting
an unrestricted caller-supplied runtime spec.

Consequently, Cloudmake never silently grants an undeclared privilege. CDI is
the explicit standard device request and is validated before Make. An image
whose target implicitly depends on root, added capabilities, services, ports,
or extra mounts is outside this profile. The generic `make --version` preflight
cannot discover every target-specific dependency, so such a target may fail as
a normal project target rather than being rejected during infrastructure
preflight. OCI alone has no standard metadata that would make that earlier
classification sound.

## Validation and failure boundary

Before target submission Cloudmake:

1. validates image and CDI syntax locally;
2. selects an available OCI execution implementation;
3. pulls or materializes the exact digest;
4. records the image operating system and architecture where the client exposes
   them, rejecting a non-Linux image but allowing the runtime to prove any
   configured cross-architecture emulation; and
5. starts a bounded `make --version` container with the selected CDI devices.

A failure in those steps is an OCI infrastructure failure and does not run the
project target. After preflight succeeds, a nonzero Make result is a project
target failure and retains the target's exit status. Both outcomes are recorded
in the normal single-run provenance. Unexpected Cloudmake exceptions remain
visible as exceptions.

## Runtime continuum

On ordinary local and SSH Linux execution surfaces, automatic selection prefers
Docker, Podman, then nerdctl. If none is ready, Cloudmake can materialize
the same OCI image using `skopeo` and `umoci` and execute its userspace through
PRoot. This fallback does not claim native namespace isolation. It can translate
the strict CDI subset Cloudmake validates—environment entries, bind mounts, and
device nodes—into explicit PRoot bindings, while rejecting hooks, ownership
overrides, and unknown edits.

The ordered choices are declared by each backend. On hosts requiring dynamic
qualification, Cloudmake probes every declared native runtime until one is
ready; the mere presence of a client executable is insufficient. CDI requests
filter out only candidates that cannot apply them. Image preflight then
validates the chosen runtime without ever replaying the project target through
another one.

For Podman, Docker, and nerdctl, Cloudmake requests a read-only image root, a
fresh writable `/tmp`, the caller's numeric non-root identity, all capabilities
dropped, and `no-new-privileges`. The only host data mount is `/workspace`;
additional device-related binds must come from an explicit CDI request. The
selected native runtime remains responsible for translating those options into
an OCI runtime specification and rejecting an unsupported combination.

Cloudmake 2.3 can source the image, literal environment, host requirements,
loopback ports, and CDI names from the project's standard Dev Container
description. The runtime policy does not change. See
[Portable Dev Container workstations](devcontainers.md).

Codespaces is deliberately outside this nested-runtime continuum. Its backend
declares `oci-native=yes`, so the selected digest becomes the provider dev
container and Make runs directly in that workstation environment. The adapter
adds its non-root SSH/Make transport surface during provider rebuild; it does
not launch Docker, Podman, crun, or PRoot for each target.

The Colab notebook backend declares one provider-qualified runtime profile.
Cloudmake installs `skopeo`, `umoci`, and `crun` when absent, materializes the
rootfs, and adapts its OCI runtime specification to Colab's managed-VM limits.
It never installs project toolchains outside the image. NVIDIA device nodes and
host driver libraries are described by a generated CDI specification and
applied to the runtime spec.

The Kaggle notebook backend declares one different constrained profile:
`skopeo` + `umoci` materialization followed by PRoot, with `setpriv` enforcing
`noNewPrivileges` and the selected identity. It needs neither a daemon
nor privileged namespace creation, which fits Kaggle's fresh managed VM. When
`nvidia.com/gpu=all` is requested, Cloudmake generates a CDI document from the
NVIDIA nodes and driver libraries actually attached to that VM and translates
the validated edits into PRoot bindings. Missing or incomplete device evidence
fails before Make; it never silently falls back to CPU. The path is intended for
trusted computational images and is not Docker-equivalent isolation.

The project workspace is bound directly into the container, so target-generated
files remain incremental and there is no per-target workspace copy. The image
root is read-only; a fresh writable `/tmp` is provided per invocation; and the
project mount is writable with `nosuid,nodev`. Make runs as UID/GID 65534 with
empty capability sets and `noNewPrivileges`. Colab's read-only cgroup hierarchy
and denied fresh procfs mount require no container cgroup, the host PID and
network namespaces, and a writable bind of host `/proc`; `/sys` is read-only.
Preflight verifies the profile on the actual VM and fails before target
submission if the managed service no longer permits it.

Live qualification also found that stock Docker and Podman profiles do not
provide this combination reliably, and direct `runc` warns that no-cgroup
operation may become an error in a future release. Cloudmake therefore does not
maintain Docker, Podman, `runc`, or bare `chroot` alternatives for Colab. This
is one explicit `crun` backend property, not a generic promise that `crun`
works on every restricted VM.

Runtime caches on local, SSH, and Colab are VM-local and disposable; they are
not copied to Google Drive. Kaggle is the deliberate exception because it has
no reusable session: when Kaggle persistence is enabled, Cloudmake includes the
downloaded runner packages and materialized image cache in the private
workspace checkpoint. A later fresh VM can reinstall from and reuse that cache
without routing the large immutable payload through the laptop. The cache is
still reconstructible and never becomes image authority; the digest-pinned
registry reference remains authoritative.

## Security boundary

Cloudmake never embeds registry credentials in source archives, runner control
files, notebooks, checkpoints, or provenance. Official OCI clients retain
custody of any registry authentication they need. Native containers receive no
host environment variables. The PRoot and Colab `crun` target processes receive
only the image's OCI environment plus safe defaults when `PATH` or `HOME` is
absent.

The Colab adapter shares the VM kernel, PID and network namespaces, and host
`/proc`; the Kaggle PRoot adapter shares the provider VM's kernel and host
interfaces without container namespaces. Neither is a strong security sandbox
for untrusted images. Neither exposes credential directories or unrelated
writable host paths. CDI names are non-secret capability requests; Cloudmake
resolves the strict JSON subset it supports and rejects unknown edits instead
of silently weakening the request. Unsupported or ambiguous device injection
fails before Make.

For the full four-axis model and backend matrix, see
[Execution environments and OCI runner](execution-environments.md). The live
evidence and exact managed-VM profile are recorded in
[Colab OCI/CDI qualification](colab-oci-qualification.md). Kaggle's deprecated,
failed remote-workstation usability evaluation is retained as a
[historical backend report](historical/kaggle-notebook.md).
