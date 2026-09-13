# Colab OCI/CDI qualification

This document records the live qualification behind Cloudmake 2.1's
`colab-notebook` bundle-runtime property. It is evidence for one maintained
backend profile, not a promise about every future Colab VM image.

## Observed execution surface

The qualification used disposable Colab T4 sessions on 2026-09-08. The observed
VM was Ubuntu 22.04.5 on x86-64 with a 6.6.122 kernel, cgroup v2 mounted
read-only, an NVIDIA T4, driver 580.82.07, and CUDA 12.8 tooling. The VM ran the
notebook process as effective root and permitted bind-mount namespaces, but it
denied a fresh procfs mount and did not provide a writable nested cgroup.

Those restrictions, not the absence of installable packages, determined the
runtime result:

| Candidate | CPU result | NVIDIA/CUDA result | Product decision |
| --- | --- | --- | --- |
| Docker daemon | daemon could start with reduced networking/storage settings; container creation failed on cgroup setup | not reached reliably | unsupported on Colab |
| Podman | CPU execution required disabled cgroups and host namespaces | GPU path conflicted with its PID-namespace requirement | unsupported on Colab |
| containerd/nerdctl | client and daemon started; image unpack/snapshot behavior was not reliable on the VM filesystem | not reached reliably | unsupported on Colab |
| direct `runc` | worked only after the same substantial OCI-spec adaptation | warned that no-cgroup execution may become an error in a future version | unsupported on Colab |
| bare `chroot` | CPU userspace could be entered | no standards-based accelerator injection path | unsupported on Colab |
| direct `crun` | passed with the qualified OCI specification | passed a real CUDA kernel through generated CDI | the sole maintained Colab profile |

Both test sessions were stopped after qualification. Google Drive and
persistent-workspace authentication were not involved.

## Maintained profile

The backend declares:

```make
BACKEND_OCI_RUNTIMES := crun
```

For every preflight and target invocation Cloudmake:

1. installs `skopeo`, `umoci`, and `crun` if the ephemeral VM lacks them;
2. verifies and materializes the digest-pinned Linux image;
3. keeps an OCI mount namespace but removes cgroup, PID, and network namespaces;
4. disables container cgroup creation and binds host `/proc` writable and
   `/sys` read-only;
5. keeps the image root read-only and binds only the project workspace, a fresh
   temporary directory, the result-receipt directory, and selected devices;
6. runs the image process as UID/GID 65534 with empty capabilities and
   `noNewPrivileges`; and
7. for `nvidia.com/gpu=all`, generates a transient CDI JSON specification from
   the allocated VM's NVIDIA device nodes, provider driver libraries, and
   `nvidia-smi` path.

The final replacement-session test compiled and ran a CUDA kernel with the
observable result:

```text
cuda-kernel-value=42 uid=65534 gid=65534
```

The exact Cloudmake integration then ran a project-provided Make target through
the pinned official ORFS image. Preflight selected `crun`; the target verified
UID/GID 65534 and reported `Tesla T4, 580.82.07` through `nvidia-smi`. The
successful invocation reused the qualification session and skipped the
unchanged source upload, confirming that bundle execution does not break
session incrementality. The disposable session was stopped and the provider
reported no active sessions afterward.

The direct CDI adapter supports environment edits, bind mounts, and existing
device nodes. It rejects hooks, node-creation overrides, YAML-only
specifications, unsupported CDI versions or fields, missing sources, and
duplicate destinations. Failure occurs during preflight, before project Make is
submitted.

## Security and compatibility boundary

The outer Colab VM is the security boundary. This profile shares its kernel,
PID namespace, network, and `/proc`; it is not a sandbox for untrusted images.
The image root is immutable for the invocation, the project workspace is the
only general writable host tree exposed, and no host environment or credential
directory is injected.

The runtime cache is ephemeral and may be repopulated from the registry on a
replacement VM. It is not part of a persistent-workspace checkpoint. Mutable
project state and immutable application bundles therefore retain separate
lifecycles and authorities.

Every new VM still receives an active preflight. If Colab changes its VM image,
kernel policy, driver layout, or available privileges, Cloudmake fails closed
instead of falling back to another unqualified Colab profile.
