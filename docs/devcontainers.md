# Portable Dev Container workstations

Cloudmake 2.3 accepts a deliberately small, fail-closed subset of the
[Dev Container specification](https://containers.dev/implementors/spec/).
It uses that standard description as the portable workstation contract while
retaining Make as the non-interactive command surface.

The normal project remains unchanged unless its developer chooses to add a Dev
Container file. The feature is explicit: merely having a configuration does not
change execution.

```sh
cloudmake --use ssh --host lab-gpu --devcontainer
# verify and route are targets supplied by this project's Makefile.
cloudmake verify
cloudmake route DESIGN=gcd
```

The bare option discovers `.devcontainer/devcontainer.json` first and then
`.devcontainer.json`. An explicit project-relative path is also accepted:

```sh
cloudmake --devcontainer=.devcontainer/cuda.json verify
```

The choice is stored only in Cloudmake's local per-project preferences. Use
`--native` to clear it. The older `--image REF@sha256:DIGEST` interface remains
the image-only shorthand and is fully compatible.

## Portable profile

Cloudmake consumes standard fields only where every qualified backend can
preserve their meaning:

| Dev Container field | Cloudmake 2.3 behavior |
| --- | --- |
| `image` | Required immutable Linux OCI reference in `REF@sha256:DIGEST` form. |
| `containerEnv`, `remoteEnv` | Literal string values are merged; `remoteEnv` wins. Host-variable interpolation and null/unset values are rejected. |
| `hostRequirements.cpus` | Positive integer, checked on the actual execution host before Make. |
| `hostRequirements.memory`, `.storage` | Byte or `kb`/`mb`/`gb`/`tb` size, checked on the actual host. |
| `hostRequirements.gpu` | `true`, `false`, or `"optional"`; required GPU presence is checked, and `true` must be paired with an explicit CDI device. Detailed core/memory objects are rejected until they can be validated honestly. |
| `forwardPorts` | Integer or `localhost:PORT`. Local and SSH backends bind only host loopback. |
| `workspaceFolder` | Omitted or exactly `/workspace`. |
| `securityOpt` | Omitted or `no-new-privileges`. Cloudmake applies its own least-privileged policy regardless. |
| `customizations.cloudmake.devices` | Optional array of CDI qualified device names, such as `nvidia.com/gpu=all`. |
| Other `customizations` | Ignored; this lets an editor retain its own metadata without changing Cloudmake execution. |

JSON with comments is accepted. Environment values in this file are project
configuration, are synchronized to the execution environment, and may appear
encoded in provider control traffic. They are not a secret channel.

This example is portable across a qualified GPU host and Colab:

```jsonc
{
  "image": "registry.example/team/cuda@sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "remoteEnv": {
    "FLOW": "smoke"
  },
  "hostRequirements": {
    "cpus": 2,
    "memory": "4gb",
    "gpu": true
  },
  "customizations": {
    "cloudmake": {
      "devices": ["nvidia.com/gpu=all"]
    }
  }
}
```

## Fail-closed boundary

Cloudmake rejects fields it cannot preserve safely and consistently before
contacting the provider. The 2.3 portable profile does not accept:

- `build`, Dockerfile, or Compose configurations;
- Dev Container Features or feature ordering;
- lifecycle hooks such as `postCreateCommand` or `postStartCommand`;
- secrets, arbitrary mounts, or arbitrary `runArgs`;
- privileged mode, added Linux capabilities, or relaxed security options;
- container/remote user changes; or
- service, shutdown, workspace-mount, and lifecycle controls.

Unknown top-level fields are also rejected. This deliberately prevents a future
Dev Container process-control field from being accepted but ignored by an older
Cloudmake release. Descriptive `$schema` and `name` fields and non-Cloudmake
editor customizations do not affect execution and are ignored safely.

These are not claims that the Dev Container standard is unsafe. They are the
parts for which the selected backends have materially different authority and
lifecycle semantics. Rejecting them prevents a configuration that works on a
privileged Docker host from being silently weakened on a managed notebook VM.

## Backend realization

The same profile may be realized differently without changing the project
target:

| Backend class | Workstation realization |
| --- | --- |
| Codespaces | Provider-native Dev Container. Selecting a changed profile rebuilds the one active workstation environment; later targets and stop/start reuse it. |
| Ordinary local or SSH Linux host | Docker first, then Podman or nerdctl when ready. The host runtime constructs the least-privileged OCI process. |
| Privilege-restricted SSH host | `skopeo` and `umoci` materialize the image; PRoot and `setpriv` execute it without a daemon, root, a user namespace, or a privileged mount. |
| Colab notebook | The single qualified `crun` adapter materializes the image and applies the managed-VM profile. |

Every non-native realization actively probes ordered runtime candidates. An
installed client is not enough: a nonfunctional Docker daemon can fall through
to Podman, nerdctl, or PRoot before image preparation and before target
submission. Cloudmake never changes runners and replays a submitted target.

Codespaces is provider-native (`oci-native=yes`); the other maintained backends
use a Cloudmake adapter (`oci-native=no`). This property describes who creates
the workstation, not whether the OCI image or Dev Container configuration is
standard.

The deprecated Kaggle adapter predates this portable profile and remains
outside release qualification.

## Ports and host requirements

`forwardPorts` creates a loopback-only access path for the lifetime of the
foreground Cloudmake target:

- local Docker/Podman/nerdctl publishes the container port on local loopback;
- an SSH backend publishes the container port on remote loopback when needed
  and opens the same local SSH tunnel with `ExitOnForwardFailure`; and
- Codespaces also receives the standard `forwardPorts` metadata in its native
  Dev Container configuration.

This is not public ingress, firewall management, or a durable service. If a
target daemonizes and Make exits, the Cloudmake-owned SSH tunnel ends. The
Colab notebook backend has no corresponding tunnel and therefore rejects a
profile containing `forwardPorts` before allocation.

Host requirements are checked on the actual machine immediately before OCI
preflight and Make. They complement backend declarations: a backend may be
qualified as GPU-capable while a particular allocation has no GPU. Codespaces
is qualified as a CPU workstation and rejects a required GPU profile before a
provider rebuild. On Colab and Lightning, `gpu: true` or a CDI device request
requires `--gpu` (or a saved GPU selection) before allocation; the Dev Container
file does not silently choose a provider product or accelerator model.
`gpu: "optional"` never causes silent allocation or device injection; CDI
remains the explicit device request.

## Security and compatibility

Cloudmake-controlled runtimes drop capabilities, request
`no-new-privileges`, use a read-only image root, expose a fresh writable `/tmp`,
and grant only the writable `/workspace` project mount plus explicitly
requested CDI device edits. Provider-native Codespaces remains subject to
metadata embedded in the selected image and is therefore a trusted-image
boundary.

This feature does not make checkpoints authoritative. Native provider storage,
managed checkpoints, OCI caches, and materialized layers are disposable ways
to reduce repeated work. Source plus the project Makefile must remain sufficient
to reconstruct the result.
