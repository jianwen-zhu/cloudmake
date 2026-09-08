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
filter out PRoot and chroot before probing. Image preflight then validates the
chosen runtime without ever replaying the project target through another one.

The Colab notebook backend uses a different restricted chroot adapter because
the managed VM does not expose a generally usable native container execution
surface. Cloudmake installs `skopeo` and `umoci` when absent, materializes the
rootfs, and uses base-VM `chroot` and narrow bind mounts to run CPU OCI images
without Docker daemon support. It never installs project toolchains outside the
image. Kaggle's fresh batch notebook path does not support this runner in 2.1.
The Colab adapter also rejects an explicit or saved GPU allocation rather than
paying for an accelerator the restricted profile cannot expose; native Make
remains available for Colab GPU projects.

The project workspace is bound directly into the chroot, so target-generated
files remain incremental and there is no per-target workspace copy. The image
root is mounted read-only with `nosuid,nodev`; a fresh writable `/tmp` is
provided per invocation; the project mount is `nosuid,nodev`; `/proc` is
read-only and `nosuid,nodev,noexec`; and only standard character devices such
as `/dev/null` and `/dev/urandom` are bound individually. Make runs as a
non-root identity. Preflight verifies these operations on the actual VM and
fails before target submission if the managed service no longer permits them.

Runtime caches are VM-local and disposable. They are not part of a persistent
workspace and are not copied to Google Drive. A replacement VM may therefore
need to pull and materialize the image again; the registry remains the source
of truth for immutable tools, while the workspace store remains the source of
truth for mutable project state.

## Security boundary

Cloudmake never embeds registry credentials in source archives, runner control
files, notebooks, checkpoints, or provenance. Official OCI clients retain
custody of any registry authentication they need. Native containers receive no
host environment variables. The PRoot and chroot target processes start with
`env -i` and receive only the image's OCI environment plus safe defaults when
`PATH` or `HOME` is absent.

The Colab adapter binds the project workspace, read-only `/proc`, and its
standard-device allowlist; it does not bind `/sys`, broad `/dev`, credential
directories, or unrelated host paths. It shares the VM kernel and network and
is therefore not a strong security sandbox for untrusted images. CDI names are
non-secret capability requests; the selected native runtime is responsible for
resolving them. Unsupported or ambiguous device injection fails before Make
instead of being ignored.

For the full four-axis model and backend matrix, see
[Execution environments and OCI runner](execution-environments.md).
