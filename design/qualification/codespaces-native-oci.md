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
The anchor is a dedicated Codespace with one top-level Git checkout under
`/workspaces`; Cloudmake rejects an absent or ambiguous anchor rather than
rebuilding an arbitrary repository.

Cloudmake multiplexes the short-lived SSH operations of one invocation through
a user-owned local control socket. `--stop` closes that socket before requesting
shutdown and returns only after GitHub confirms `Shutdown`; the next target can
therefore report a genuine `resource=started` transition.

Provider state inspection, SSH-configuration discovery, and environment
preparation happen before Make is submitted. Cloudmake retries only positively
classified transient GitHub control-plane or tunnel failures during that safe
pre-submission phase. It does not retry a target after execution begins. A
current GitHub CLI is recommended; the v2.2 live gate was qualified with the
2.100.x line.

The project workspace also remains below `/workspaces`, so an environment
rebuild does not discard source synchronization state or project-generated
files. Those files remain a disposable acceleration cache: source plus Make
must still be sufficient to reconstruct them after provider deletion.

## Network boundary

GitHub documents public-Internet outbound connections as part of the
[Codespaces security model](https://docs.github.com/en/codespaces/reference/security-in-github-codespaces),
so this backend declares `internet-outbound=yes`. The v2.2 consumer gate
exercises that capability through ECE326's actual package, Git, and model
downloads rather than a synthetic connectivity probe.

Codespaces blocks direct incoming Internet connections. Applications can be
exposed through GitHub's
[port-forwarding service](https://docs.github.com/en/codespaces/developing-in-a-codespace/forwarding-ports-in-your-codespace),
whose private, organization, and public visibility options depend on account
and organization policy. The backend therefore declares
`internet-inbound=conditional`. Cloudmake 2.3 maps a selected portable Dev
Container's `forwardPorts` into the provider-native configuration and creates a
local-loopback SSH tunnel while the foreground target runs. It does not request
public visibility. Its authenticated SSH tunnel is a provider control channel
and, by the backend contract, is not public inbound access.

Cloudmake v2.2 qualifies this provider capability through a separate live gate:
a project Make target starts a loopback HTTP listener, `gh codespace ports
forward` creates an authenticated private tunnel, and the host retrieves a
unique marker before both listener and compute are stopped. Public visibility
is deliberately outside the gate. The v2.3 cross-backend gate also verifies the
standard `forwardPorts` mapping; the earlier explicit CLI gate remains useful
provider evidence.

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

## Consumer qualification

The v2.2 release gate uses the same Codespace and digest-pinned Python
workstation image for two independent course consumers. ECE326 runs its clean
Lab 1 setup, 17-test suite, Bottle workload, and paired Lab 4 calibration (36
reference and 36 candidate tests, all repetitions complete, Gold). A bounded
ECE467 CPU path runs all project starter checks, CPU AXPY and GEMM references,
and fast llm.c conformance and checkpoint-reload tests. CUDA, TileLang, model
downloads, and long ECE467 benchmarks are deliberately excluded because this
backend is qualified as CPU-only.

This gate tests application-level use of the provider-native OCI environment;
the separate workstation gate tests image transitions, stop/start reuse,
artifact collection, neutral-anchor restoration, and confirmed shutdown.
