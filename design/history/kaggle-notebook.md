# Historical backend report: Kaggle notebook

> **Status:** Deprecated and not recommended for Cloudmake's remote-workstation
> workflow. The implementation remains available for compatibility and coarse
> batch experimentation, but it is not a Cloudmake 2.1 release qualification
> surface. Every target receives a fresh VM and repeats checkpoint restoration,
> OCI materialization, and checkpoint publication; the measured ECE467
> workspace was roughly 14.5 GB per cycle.

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

Projects that deliberately override `$HOME` with a provider-specific absolute
path must redirect that state themselves. The ECE467 acceptance project, for
example, defaults to `/content/.ece467-labs` whenever `/content` exists. Its
existing `STATE_ROOT` Make variable is therefore set to
`$(HOME)/.cache/ece467-labs` by the Kaggle gate; Cloudmake does not guess or
rewrite project paths.

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
`skopeo`, `umoci`, a checksum-pinned PRoot 5.4.1 binary, and `setpriv`;
materialize the exact digest-pinned Linux image; run a bounded `make --version`
preflight; and invoke the project target at most once. With persistence
enabled, downloaded packages and the verified OCI layout are included in the
private checkpoint to avoid a registry pull on every fresh VM. The derived
rootfs is discarded before publication and reconstructed from that layout on
the next VM, avoiding a second copy of the image at the cost of per-target
unpack time. The registry remains the authority for immutable image identity.

PRoot provides userspace path translation, not container isolation. Cloudmake
runs the image as UID/GID 65534 with a clean image-derived environment, a
writable project/home/tmp surface, conventional `/proc` and `/sys` kernel API
views, and explicitly requested CDI bindings. Empty capability sets,
`noNewPrivileges`, the unprivileged identity, and bounded mounts remain in
force. This profile is for trusted automated computational images.

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

Initial end-to-end Cloudmake OCI attempts failed safely before Make because VMs
whose returned metadata confirmed `enable_internet=true` could not resolve
Ubuntu package hosts. Two independent clean ECE326 Lab 1 jobs (private kernel
versions 2 and 3, each receiving a fresh VM) reproduced the same behavior. The
cause was an unmet account prerequisite, not a permanent Kaggle egress policy:
the account was phone-verified but not Persona identity-verified, and the
notebook editor omitted its Internet control.

After Persona verification on 2026-09-08, the same notebook reported Internet
on without a manual toggle. A live UI console probe resolved `pypi.org` and
received HTTP 200. More importantly, private kernel version 4 was then submitted
through the unchanged Kaggle CLI path with `enable_internet=true`; its network
preflight passed, its project-provided ECE326 `setup` target downloaded pinned
PyPI and model assets, cloned the pinned GitHub oracle, completed successfully,
and published the first checkpoint. This disproves the earlier hypothesis that
CLI-submitted jobs are inherently offline.

Cloudmake probes requested internet before target submission, records an
infrastructure failure when it is absent, and leaves the checkpoint head
unchanged. The two pre-verification attempts recorded
`target_submission=not_submitted` and `retry_safe=true`; neither created a
checkpoint head. The post-verification target executed exactly once and
advanced the head. Outbound Internet remains `conditional`, because account
eligibility and a per-job provider decision still apply, but it is now live
qualified for a CLI-submitted CPU job. A cold OCI workspace needs package and
registry network access; a warm checkpoint can reuse its cached packages and
image. Cloudmake never retries or replays the project target. The offline
PRoot/CDI implementation is fully exercised with provider doubles.

The full ECE326 Kaggle course gate subsequently passed, including fresh-job
checkpoint recovery. A separate live T4 OCI/CDI `verify` run also passed with
PyTorch 2.7.1+cu128, CUDA 12.8, and a Tesla T4, qualifying registry pull,
least-privileged PRoot execution, device discovery, `/proc` and `/sys` kernel
views, and checkpoint publication. These results qualify the mechanism; they do
not substitute for the stricter ECE467 application gate.

The first live ECE467 native-image attempt sharpened the same boundary. Its
`bootstrap` target succeeded under `/content/.ece467-labs`, but that directory
was correctly absent from the next fresh VM's managed workspace; the target
then repeated installation. Kaggle's native PyTorch image also lacked the
LibTorch CUDA development headers required by libttl. This is why the release
gate uses the project's `STATE_ROOT` override plus an immutable PyTorch CUDA
development OCI image and `nvidia.com/gpu=all`, instead of treating Kaggle's
native notebook image as the course tool bundle.

The ECE467 gate then tested three immutable PyTorch CUDA development images.
PyTorch 2.7.1 and 2.10 lacked the `c10/cuda/CUDAEvent.h` interface consumed by
the current libttl source. PyTorch 2.11 supplied that interface. The first link
failed at `-lcuda`, but exact-image inspection and a stock-Docker reproduction
showed that this was not a missing bundle artifact: NVIDIA's official
`libcuda.so` link-time stub is present at `/usr/local/cuda/lib64/stubs`, while
the image intentionally omits that directory from its runtime
`LD_LIBRARY_PATH`. A stock-Docker link and the unchanged ECE467 `ttl-build`
target both passed when that conventional development path was supplied through
`LIBRARY_PATH`.

The Kaggle gate therefore uses the ordinary project Make assignment
`LIBRARY_PATH=/usr/local/cuda/lib64/stubs`; Cloudmake does not infer, inject, or
special-case it. With that image contract made explicit, a live `ttl-prelabs`
run built libttl and passed all four prelabs, then published a 14.50 GB private
checkpoint. A following fresh T4 VM restored that checkpoint, reused the OCI
layout and Python environment, rehydrated three guest-absolute virtual-
environment links, verified PyTorch 2.11.0+cu128, CUDA 12.8, and Tesla T4, and
published the alternating checkpoint. This qualifies the image integrity,
OCI/CDI execution, and cross-VM recovery path. Two subsequent ECE467 CUDA
workload targets passed. The broader course sequence was intentionally stopped
once the repeated transfer cost proved the backend impractical; it is no longer
a release gate. The unfinished sequence is not an unresolved OCI runtime or
image defect, but neither is it claimed as completed acceptance.

The large image also exposes a practical limitation: preserving its compressed
OCI layers in a Kaggle checkpoint avoids a fresh registry pull but still moves
roughly 14.5 GB through every fresh-job restore/publication cycle and must
rematerialize the rootfs. The measured verification cycle took about 35 minutes
even though the project target itself was short. This is honest
`session-reuse=no` behavior and a performance constraint of this backend, not a
claim of workstation-like target latency.

Release qualification must retain fake-provider coverage for slot alternation,
fresh-VM restore, source reconciliation, target-at-most-once behavior, failed
head publication, credential non-disclosure, OCI preflight, PRoot CDI
translation, hard links, and multi-gigabyte streaming digests. Live gates are
kept separate because provider capacity and networking are not deterministic.
