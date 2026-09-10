# Cloudmake 2.4: single-node GCP remote workstation

## Objective

Cloudmake 2.4 will add one Google Compute Engine backend that makes an already
provisioned, single-node VM behave like the other Cloudmake remote workstations:

```text
cloudmake TARGET
  -> validate account, project, zone, instance, quota, and cost boundary
  -> start or reuse the named VM
  -> incrementally synchronize the local project
  -> qualify the selected Dev Container and CDI requirements
  -> execute the project Make target exactly once
  -> leave generated work on Persistent Disk for the next invocation
```

The same backend must represent both an eligible
[free-tier `e2-micro` CPU VM](https://docs.cloud.google.com/free/docs/free-cloud-features)
and paid CPU or accelerator machines, including a user-provisioned G4 VM. The
backend reports what the selected resource actually is; it never labels a GPU
as free merely because some Compute Engine usage has a free allowance.

## Responsibility boundary

The user or infrastructure administrator provisions the project, network,
instance, boot image, Persistent Disk, IAM policy, quota, and billing account.
Cloudmake does not create or delete those resources in 2.4. This preserves the
existing boundary between workstation execution and infrastructure management.

Cloudmake owns the operational adapter:

- use the official [`gcloud compute ssh`](https://docs.cloud.google.com/sdk/gcloud/reference/compute/ssh)
  path and its existing local authentication;
- identify, validate, start, stop, and reconnect to the named VM;
- serialize concurrent operations for that resource;
- use incremental SSH/rsync synchronization without cloning a repository;
- treat the instance filesystem as native stop-persistent storage;
- qualify Docker first for the standard Dev Container contract, with the common
  least-privileged SSH runtime rules available when the host is restricted;
- validate requested CDI devices against the VM's real drivers and hardware;
- expose separate inbound and outbound network capability; and
- report machine type, accelerator, lifecycle state, quota pressure, and the
  fact that the resource can incur charges in a compact execution context.

Project Makefiles remain unchanged. Native Make remains the default, and an
explicit Dev Container remains an optional workstation description rather than
a mandatory project format.

## Persistence model

Compute Engine Persistent Disk is the backend's native persistence service.
[Stopping an instance](https://docs.cloud.google.com/compute/docs/instances/suspend-stop-reset-instances-overview)
retains its attached disks and configuration, so stopping compute does not
require packing, uploading, restoring, or decrypting a Cloudmake checkpoint.
`--persist` therefore retains the existing high-level contract but reports
native persistence and performs no checkpoint transfer.

Persistent Disk is an optimization, not an authority. A deleted or corrupted VM
must remain recoverable from source, the declared workstation image, and project
Make targets. GCS is not required by this backend and is not a replacement for
the disk in the 2.4 release.

## Credential and billing boundary

Long-lived Google credentials remain exclusively in the official host client.
Cloudmake must not upload Application Default Credentials, OAuth refresh tokens,
service-account keys, SSH private keys, or `gcloud` configuration to the VM,
project, provenance, artifact bundle, or persistent disk.

Compute Engine's free allowance is conditional and excludes GPUs and TPUs.
Cloudmake can describe observed quota, machine configuration, lifecycle, and
billing exposure, but it cannot guarantee zero cost. A paid-capable resource
must produce an explicit compact warning before Cloudmake starts it. Provider
pricing remains authoritative.

## Non-goals

- No multi-node or distributed execution.
- No Terraform, VPC, IAM, project, billing-account, quota, disk, or VM creation.
- No generic cloud scheduler or background daemon.
- No automatic target replay after submission.
- No GCS checkpoint requirement and no attempt to make Colab a GCP VM.
- No promise that a provider resource is free.

## Release qualification

The 2.4 release requires:

1. Offline fake-provider coverage for absent authentication, invalid project or
   zone, missing instance, quota failure, start/reuse/stop, ambiguous readiness,
   interrupted SSH, and cost-warning behavior.
2. A live eligible `e2-micro` CPU gate proving start, incremental source reuse,
   Dev Container execution, Persistent Disk survival across stop/start, outbound
   access, bounded inbound forwarding, and clean stop.
3. A live paid GPU gate on the selected G4 profile proving driver and CDI
   qualification, immutable OCI execution, target-at-most-once behavior, quota
   diagnostics, and stop without deleting the disk.
4. The full existing local, native Colab, Codespaces, and host-SSH regression
   suite unchanged.
5. Credential scans showing that no Google or SSH credential entered source,
   control files, logs, provenance, artifacts, or the remote workspace.

The CPU and GPU gates may use different machine profiles, but they qualify one
backend and one user-facing Make workflow.
