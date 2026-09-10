# GCP remote-workstation live gate

This local-only gate qualifies one already-provisioned Compute Engine VM. It
never creates or deletes a project, VM, disk, firewall rule, IAM binding, or
billing resource. Both profiles stop the VM at the end and retain its attached
disk. Google Cloud charges for retained disks and other attached resources may
continue after compute stops.

The CPU profile proves lifecycle start/reuse/stop, observed environment facts,
digest-pinned Dev Container execution, incremental generated state, outbound
HTTPS, loopback inbound forwarding, artifact collection, and disk survival over
stop/start:

```sh
export CLOUDMAKE_TEST_LIVE_GCP=1
export GCP_PROJECT=PROJECT
export GCP_ZONE=us-central1-a
export GCP_INSTANCE=E2_MICRO_VM
GCP_GATE=cpu tests/acceptance/gcp-workstation/run.sh /tmp/cloudmake-gcp-cpu-evidence
```

Use `GCP_TUNNEL_THROUGH_IAP=yes` for an IAP-only VM. The configured image is
public and digest-pinned. The VM still needs a qualified Docker, Podman,
nerdctl, or restricted PRoot execution path.

The paid G4 profile additionally proves real NVIDIA driver discovery, CDI
device injection, and immutable CUDA OCI execution:

```sh
export CLOUDMAKE_TEST_LIVE_GCP=1
export GCP_PROJECT=PROJECT
export GCP_ZONE=ZONE
export GCP_INSTANCE=G4_VM
export GCP_G4_IMAGE=REGISTRY/CUDA-TOOLS@sha256:64_LOWERCASE_HEX_DIGITS
GCP_GATE=g4 tests/acceptance/gcp-workstation/run.sh /tmp/cloudmake-gcp-g4-evidence
```

The G4 image must contain Make and `nvidia-smi` must be usable through the
selected CDI device (default `nvidia.com/gpu=all`). `GCP_G4_CDI_DEVICE` may name
a more specific qualified device. Because G4 is paid, run the bounded gate,
inspect the evidence, confirm `cloudmake --status` reports stopped, and verify
the provider billing console. No live GCP test belongs in hosted CI and no
Google or SSH credentials belong in its evidence directory.
