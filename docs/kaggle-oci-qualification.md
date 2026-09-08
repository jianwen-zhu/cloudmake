# Kaggle checkpoint and OCI qualification

This document records the managed-VM evidence behind Cloudmake 2.1's Kaggle
profile. It is a bounded qualification of one provider surface, not a guarantee
that Kaggle scheduling, internet access, accelerators, or base images remain
unchanged.

## Backend contract

Kaggle declares:

```text
session-reuse=no
persistence=checkpoint
oci-runtimes=proot
internet-inbound=no
internet-outbound=conditional
```

Each project target receives a fresh batch VM. Persistence does not change that
fact: it preserves the logical workspace, not the process, VM, or cheap target
dispatch. Cloudmake alternates two private notebook-output slots and attaches
only the locally recorded last-good slot to the next job as a Kaggle
`kernel_source`. A successful target publishes the successor and atomically
advances the local head. Target or infrastructure failure leaves the old head
unchanged.

The adapter sets `HOME` and the XDG cache, configuration, and state roots under
that logical workspace before invoking Make. This keeps project-managed tool
installations outside the synchronized source tree while ensuring they are part
of the next checkpoint. It is important for unmodified projects that correctly
place large generated environments under `$HOME/.cache`.

The checkpoint is provider-private rather than Cloudmake-encrypted. Its archive
travels between Kaggle jobs inside the provider and never through the laptop.
Kaggle credentials remain with the official CLI and are absent from generated
notebooks, checkpoint payloads, and receipts.

## Observed managed VM

Live probes on 2026-09-08 used Kaggle CLI 2.2.4 and private notebook versions.
The observed CPU execution VM had:

- UID 0 and `CAP_SYS_CHROOT`, but no `CAP_SYS_ADMIN`;
- no working new user or mount namespace;
- cgroup v2 mounted read-only;
- executable ext4 storage at `/kaggle/working`;
- no `/dev/fuse` or `/dev/kvm`; and
- no preinstalled Docker, Podman, crun, PRoot, skopeo, or umoci client
  (`setpriv` was present in the base VM).

Those restrictions do not qualify a stock daemon-based OCI runtime. The
backend instead declares one narrow adapter: transiently install or restore
`skopeo`, `umoci`, PRoot, and `setpriv`; materialize the exact digest-pinned
Linux image; run a bounded `make --version` preflight; and invoke the project target at
most once. With persistence enabled, downloaded packages and the materialized
image are included in the private checkpoint to avoid a registry pull on every
fresh VM. The registry remains the authority for immutable image identity.

PRoot provides userspace path translation, not container isolation. Cloudmake
runs the image as UID/GID 65534 with a clean image-derived environment and only
the project workspace plus explicitly requested CDI bindings. This profile is
for trusted automated computational images.

## CDI boundary

The qualified Kaggle CDI surface is deliberately small:

```text
nvidia.com/gpu=all
```

On each run Cloudmake derives a JSON CDI document from the NVIDIA device nodes,
driver libraries, and `nvidia-smi` actually visible in that VM. Its common
strict CDI validator accepts environment edits, bind mounts, and device nodes;
the PRoot adapter translates those into explicit bindings. Hooks, ownership
overrides, missing nodes, and unknown edits fail before Make. An accelerator
request never silently degrades to CPU.

During this qualification, Kaggle accepted both T4 and L4 metadata requests but
one completed probe was provisioned without NVIDIA nodes and with a CPU-only
PyTorch build. Cloudmake therefore correctly treats requested metadata as
intent, not proof. A completed GPU CDI acceptance remains required before the
profile can claim a specific current Kaggle accelerator image as live-verified.

## Live evidence and provider limitations

A two-job private-kernel spike passed provider-side checkpoint chaining. The
subsequent end-to-end Cloudmake gate also passed: a native `provision` target
published slot A, a fresh VM attached it as a `kernel_source`, discovered the
provider-chosen input mount by receipt identity, restored the marker, ran the
project's `verify` target, and published slot B. The laptop downloaded only the
log and receipts, not the checkpoint payload.

End-to-end Cloudmake OCI attempts failed safely before Make because VMs whose
returned metadata confirmed `enable_internet=true` could not resolve Ubuntu
package hosts. No checkpoint head advanced. `enable_internet=true` is therefore
a request, not a reachability guarantee. Two independent September 2026 clean
ECE326 Lab 1 jobs (private kernel versions 2 and 3, each receiving a fresh VM)
reproduced the same behavior: Kaggle accepted the setting but the batch VM
could not resolve PyPI. This is reproducible for the tested CLI/account path,
not evidence that Kaggle permanently forbids egress; the backend consequently
declares outbound Internet `conditional`, not `no`.

Cloudmake probes requested internet before target submission, records an
infrastructure failure when it is absent, and leaves the checkpoint head
unchanged. Both ECE326 attempts recorded `target_submission=not_submitted` and
`retry_safe=true`; neither created a checkpoint head. A cold OCI workspace
needs package and registry network access; a warm checkpoint can reuse its
cached packages and image. Cloudmake never retries or replays the project
target. The offline PRoot/CDI implementation is fully exercised with provider
doubles, but a successful live cold pull and the ECE326/ECE467 course gates
remain explicit release blockers rather than claimed results.

Release qualification must retain fake-provider coverage for slot alternation,
fresh-VM restore, source reconciliation, target-at-most-once behavior, failed
head publication, credential non-disclosure, OCI preflight, PRoot CDI
translation, hard links, and multi-gigabyte streaming digests. Live gates are
kept separate because provider capacity and networking are not deterministic.
