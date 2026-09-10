# Codespaces native OCI environment

GitHub Codespaces is not treated as a generic SSH VM with a nested container
runtime. Its dev container is the provider-managed OCI execution environment.
The backend therefore declares:

```make
BACKEND_OCI_NATIVE := yes
BACKEND_OCI_RUNTIMES := none
```

`oci-native=yes` means the provider constructs the environment from the
selected digest-pinned OCI image. `oci-runtimes=none` means Cloudmake does not
start Docker, Podman, crun, or PRoot inside that environment.

A Codespace has exactly one active workstation image at a time. Cloudmake
therefore serializes image reconciliation, source synchronization, and target
execution by Codespace name, even when multiple local projects select the same
resource from this host. Separate hosts must not concurrently control the same
Codespace.

## Lifecycle

The neutral Cloudmake anchor supplies the initial SSH endpoint. When a project
selects an image, the backend derives a dev-container configuration from that
immutable reference and asks Codespaces to rebuild. The selected image and
adapter revision are recorded in the provider-persistent `/workspaces` tree.
Later targets using the same image skip the rebuild. Selecting another image
rebuilds the environment; selecting `--native` restores the neutral anchor.

The project workspace also remains below `/workspaces`, so an environment
rebuild does not discard source synchronization state or project-generated
files. Those files remain a disposable acceleration cache: source plus Make
must still be sufficient to reconstruct them after provider deletion.

## Adapter boundary

A general OCI image is not automatically a usable Codespaces development
container. The adapter must provide and validate the small Cloudmake transport
surface:

- an SSH server accepted by `gh codespace ssh`;
- a non-root execution identity;
- `make`, `rsync`, and `tar`, or a Debian-compatible `apt-get` from which the
  adapter can install them;
- a Linux image matching the Codespace architecture; and
- no requested CDI device, because the qualified Codespaces backend is CPU.

The adapter may add transport tools while constructing the dev container, but
it does not add application libraries or change the project's Make targets.
Failure to construct or validate this surface is an environment preparation
failure. No project target has been submitted and Cloudmake must not replay it.

## Security boundary

Cloudmake does not request Docker-in-Docker, privileged mode, added Linux
capabilities, host-device mounts, or a host Docker socket. Project Make runs as
the adapter's non-root user inside the Codespaces dev container. GitHub owns
the VM/container isolation and image pull; the GitHub CLI owns authentication.
Cloudmake stores only the non-secret image reference, digest, Codespace name,
and preparation receipt.

The standard OCI image configuration does not by itself declare arbitrary
privilege or hardware requirements. Consequently, `oci-native=yes` is not a
promise that every OCI image is compatible. Cloudmake qualifies the explicit
surface above and rejects unsupported CDI or adapter requirements before Make
execution.

The Dev Container specification also permits an OCI image to carry a
`devcontainer.metadata` label. GitHub may merge that provider-native metadata,
including lifecycle commands or privilege requests, while constructing the
Codespace. Cloudmake adds no privileged mode, capabilities, security-option
relaxation, host socket, or device mount of its own, but it cannot strip or
preflight provider-consumed image metadata before GitHub's build service pulls
the image. A selected workstation image is therefore trusted input and remains
subject to GitHub's policy. This is a documented provider-native boundary, not
the stricter Cloudmake-controlled OCI adapter boundary used on Colab and other
hosts.
