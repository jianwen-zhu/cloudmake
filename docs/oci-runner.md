# OCI/CDI runner

Cloudmake 2.1 can execute an unchanged Make project with tools supplied by a
digest-pinned OCI image. This runner is independent of the selected backend and
of optional persistent workspaces.

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
Podman, Docker, then nerdctl. If none is installed, Cloudmake can materialize
the same OCI image using `skopeo` and `umoci` and execute its userspace through
PRoot. This fallback is deliberately less capable: it cannot apply CDI device
edits and does not claim native namespace isolation.

The ordered choices are declared by each backend. On hosts requiring dynamic
qualification, Cloudmake probes every declared native runtime until one is
ready; the mere presence of a client executable is insufficient. CDI requests
filter out PRoot before probing. Image preflight then validates the chosen
runtime without ever replaying the project target through another one.

The Colab notebook backend declares one provider-qualified runtime profile.
Cloudmake installs `skopeo`, `umoci`, and `crun` when absent, materializes the
rootfs, and adapts its OCI runtime specification to Colab's managed-VM limits.
It never installs project toolchains outside the image. NVIDIA device nodes and
host driver libraries are described by a generated CDI specification and
applied to the runtime spec. Kaggle's fresh batch notebook path does not support
this runner in 2.1.

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

Runtime caches are VM-local and disposable. They are not part of a persistent
workspace and are not copied to Google Drive. A replacement VM may therefore
need to pull and materialize the image again; the registry remains the source
of truth for immutable tools, while the workspace store remains the source of
truth for mutable project state.

## Security boundary

Cloudmake never embeds registry credentials in source archives, runner control
files, notebooks, checkpoints, or provenance. Official OCI clients retain
custody of any registry authentication they need. Native containers receive no
host environment variables. The PRoot and Colab `crun` target processes receive
only the image's OCI environment plus safe defaults when `PATH` or `HOME` is
absent.

The Colab adapter shares the VM kernel, PID and network namespaces, and host
`/proc`; it is therefore not a strong security sandbox for untrusted images.
It does not expose credential directories or unrelated writable host paths.
CDI names are non-secret capability requests; Cloudmake resolves the strict JSON
subset it supports and rejects unknown edits instead of silently weakening the
request. Unsupported or ambiguous device injection fails before Make.

For the full four-axis model and backend matrix, see
[Execution environments and OCI runner](execution-environments.md). The live
evidence and exact managed-VM profile are recorded in
[Colab OCI/CDI qualification](colab-oci-qualification.md).
