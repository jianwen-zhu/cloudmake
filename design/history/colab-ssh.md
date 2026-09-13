# Historical backend report: paid Colab SSH

> **Status:** Deprecated. The adapter remains available for CLI compatibility,
> but it is not a Cloudmake release-qualification surface and is scheduled for
> removal at the next major compatibility boundary.

The `colab-ssh` backend provides SSH and rsync through the Colab CLI's
WebSocket proxy. It is a managed Colab runtime, not a Google Compute Engine VM:
Colab still owns its lifecycle, restrictions, capacity, and entitlement.

Cloudmake retired this path because it duplicates two clearer supported models:

- `colab` uses the native notebook/runtime API for restricted managed Colab;
- `ssh` uses an already provisioned conventional VM, including a GCP VM.

Unlike native Colab, the SSH adapter has no qualified cross-VM persistence
service. Unlike a future full GCP backend, it does not manage Compute Engine
lifecycle, persistent disks or object storage, IAM, quotas, or billing. No
successful paid SSH release gate was retained.

## Compatibility use

Existing invocations continue to work during the 2.x line:

```sh
COLAB_IDENTITY=/path/to/id_ed25519 cloudmake -b colab-ssh TARGET
cloudmake -b colab-ssh --stop
```

Prerequisites are the official Colab CLI, a paid Colab plan with the required
entitlement or balance, OpenSSH, rsync, and an Ed25519 or ECDSA private key.
Cloudmake's doctor can check the installed tools, key, and local Colab login,
but provider entitlement can only be established by attempting the connection.

New projects should choose native `colab`, `ssh`, or `codespaces` instead.
