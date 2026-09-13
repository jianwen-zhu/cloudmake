# Dev Container workstation contract

For a conceptual introduction to application bundles, OCI image/runtime
layers, CDI devices, Dev Container implementations, and the portable adapter,
read [Day 3: Dev Container workstations](../tutorials/day3-devcon.md).

Cloudmake accepts the standard
[Dev Container specification](https://containers.dev/implementors/spec/) as a
workstation configuration, analyzes the behavior it requires, and dynamically
qualifies one realization. The project still exposes only its ordinary Make
targets. Cloudmake does not silently discard standard behavior to fit a weaker
backend. This file is the complete user-facing contract for that behavior.

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

## Configuration and qualification

Every recognized field has one of three meanings:

1. **Portable behavior** has one stable meaning on every backend that declares
   support for it.
2. **Advisory metadata**, such as `$schema`, `name`, and editor-specific
   customizations, has no process or resource effect and may be ignored.
3. **Capability-requiring behavior**, such as image builds, Features,
   lifecycle commands, user selection, mounts, ports, privilege, or devices,
   is accepted only when one backend realization can preserve it completely.

The accepted advisory set is closed. Unknown fields are not assumed harmless.
Cloudmake derives a required-capability set from the complete configuration,
checks static backend declarations before allocation where possible, and
qualifies runtime-dependent requirements on the actual machine. Failure always
occurs before the project target is submitted.

One realization must satisfy the entire contract. Cloudmake does not combine
partial capability sets from multiple adapters, and dynamic qualification may
narrow a backend's declared ceiling but never widen it.

## Adapter-supported behavior

The portable adapter defines these behaviors. A backend may support only a
subset and rejects the others before Make:

| Dev Container field | Portable adapter behavior |
| --- | --- |
| `image` | Required immutable Linux OCI reference in `REF@sha256:DIGEST` form. Tagged references require a Dev Container implementation that declares and dynamically validates tag resolution. |
| `containerEnv`, `remoteEnv` | Literal string values are merged; `remoteEnv` wins. Host-variable interpolation and null/unset values are rejected. |
| `hostRequirements.cpus` | Positive integer, checked on the actual execution host before Make. |
| `hostRequirements.memory`, `.storage` | Byte or `kb`/`mb`/`gb`/`tb` size, checked on the actual host. |
| `hostRequirements.gpu` | `true`, `false`, or `"optional"`; required GPU presence is checked, and `true` must be paired with an explicit CDI device. Detailed core/memory objects are rejected until they can be validated honestly. |
| `forwardPorts` | Integer or `localhost:PORT`. Local and SSH backends bind only host loopback; Colab rejects the field because it has no corresponding tunnel. |
| `workspaceFolder` | Omitted or exactly `/workspace`. |
| `securityOpt` | Omitted or `no-new-privileges`. Cloudmake applies its own least-privileged policy regardless. |
| `customizations.cloudmake.devices` | Optional array of CDI qualified device names, such as `nvidia.com/gpu=all`. |
| Other `customizations` | Ignored; this lets an editor retain its own metadata without changing Cloudmake execution. |

JSON with comments is accepted. Environment values in this file are project
configuration, are synchronized to the execution environment, and may appear
encoded in provider control traffic. They are not a secret channel.

This example is portable across a supported GPU host and Colab when their live
resources qualify:

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

Richer standard fields become explicit required behavior rather than parser
errors. The declared local reference implementation currently adds tagged
images, Dockerfile/image builds, Features, create-phase lifecycle commands,
standard remote/container user selection, workspace layout, process control,
and restrictive security policy. It invokes the reference Dev Container CLI
over the existing local Docker service, records the actual image
digest or derived image ID, and reuses the same prepared container while its
configuration fingerprint is unchanged.

## Fail-closed boundary

Cloudmake rejects statically impossible requirements before contacting the
provider. Requirements that depend on the assigned runtime, driver, or device
are rejected after live qualification but always before Make. No maintained
backend currently accepts:

- Compose configurations;
- secrets, arbitrary mounts, arbitrary `runArgs`, or host lifecycle commands;
- privileged mode, added Linux capabilities, or relaxed security options;
- port attributes, published ports, attach hooks, or general start/shutdown
  lifecycle controls; or
- interpolated host environment values and detailed GPU requirement objects.

Unknown top-level fields are also rejected. This deliberately prevents a future
Dev Container process-control field from being accepted but ignored by an older
Cloudmake release. Descriptive `$schema` and `name` fields and non-Cloudmake
editor customizations do not affect execution and are ignored safely.

Errors name both the semantic capability and the standard field that required
it, for example `lifecycle-create (postCreateCommand)`. The complete
configuration must fit one execution path; the adapter and implementation
capability sets are never combined to manufacture a pass.

These are not claims that the Dev Container standard is unsafe. They are the
parts for which the selected backends have materially different authority and
lifecycle semantics. Rejecting them prevents a configuration that works on a
privileged Docker host from being silently weakened on a managed notebook VM.

## Backend realization

The same configuration may be realized differently without changing the project
target:

| Backend class | Workstation realization |
| --- | --- |
| Local, richer standard behavior | Reference Dev Container CLI over Docker; the prepared container and create-phase receipt are reused by configuration fingerprint. |
| Codespaces | Provider-native image-backed Dev Container for the portable subset. Selecting a changed configuration rebuilds the one active workstation environment; later targets and stop/start reuse it. |
| Ordinary local or SSH Linux host, portable subset | Docker first, then Podman or nerdctl when ready. The host runtime constructs the least-privileged OCI process. |
| Privilege-restricted SSH host | `skopeo` and `umoci` materialize the image; PRoot and `setpriv` execute it without a daemon, root, a user namespace, or a privileged mount. |
| Colab notebook | The single declared `crun` adapter materializes the image and is dynamically qualified against each managed VM. |

Every non-native realization actively probes ordered runtime candidates. An
installed client is not enough: a nonfunctional Docker daemon can fall through
to Podman, nerdctl, or PRoot before image preparation and before target
submission. Cloudmake never changes runners and replays a submitted target.

Codespaces is provider-native (`oci-native=yes`); the other maintained backends
use a Cloudmake adapter (`oci-native=no`). This property describes who creates
the workstation, not whether the OCI image or Dev Container configuration is
standard. Dev Container semantic capabilities are declared separately as
adapter and native capability sets; these describe what can be honored, not
merely which executable happens to be installed.

Product qualification remains separate from implementation capability.
Lightning Studio SSH implements this subset through the common SSH adapter but
remains `unqualified` until its live release gate succeeds and the evidence is
retained. Paid Colab SSH also shares the implementation, but is deprecated
because it adds no distinct qualified workstation capability. Selecting either
prints that status and reason.

The deprecated Kaggle adapter predates this portable subset and remains
outside release qualification.

The exact static capability ceiling is deliberately visible rather than
inferred from the provider brand:

| Backend | Product status | Adapter semantics | Native semantics |
| --- | --- | --- | --- |
| `local` | supported | digest image, literal environment, host requirements, loopback ports, CDI, restrictive security policy | digest/tag image, image build, Features, create lifecycle, user selection, literal environment, host requirements, workspace layout, process control, restrictive security policy |
| `colab-notebook` | supported | digest image, literal environment, host requirements, CDI, restrictive security policy | none |
| `codespaces-ssh` | supported | none | digest image, literal environment, host requirements, loopback ports, restrictive security policy |
| `host-ssh` | supported | digest image, literal environment, host requirements, loopback ports, CDI, restrictive security policy | none |
| `gcp-compute-ssh` | unqualified | digest image, literal environment, host requirements, loopback ports, CDI, restrictive security policy | none |
| `lightning-studio-ssh` | unqualified | digest image, literal environment, host requirements, loopback ports, CDI, restrictive security policy | none |
| `colab-ssh` | deprecated | digest image, literal environment, host requirements, loopback ports, CDI, restrictive security policy | none |
| `kaggle-notebook` | deprecated | none | none |

“Native semantics” means the provider constructs the workstation, as
Codespaces does. “Adapter semantics” means Cloudmake supplies the missing
execution machinery. Product status is an independent release-quality
statement. Each backend also declares the order in which its realizations are
considered. Dynamic runtime, host, device, and network probes may narrow a
static ceiling for a particular invocation; they never widen it.

## Image identity and registry access

Digest references are used directly. A backend that accepts an image tag
resolves it through its existing registry integration and records the source
reference, resolved manifest digest or derived image identity, target platform,
configuration fingerprint, and logical workstation identity. Later targets
reuse that resolution while the same logical workstation remains valid. A
configuration change or workstation reconstruction resolves the tag again;
Cloudmake never changes the image merely because a remote tag moved.

Registry authentication remains with the selected runtime, provider service,
credential helper, or workload identity. Cloudmake does not read, upload,
persist, or print registry credentials. A backend that cannot access a private
reference using its existing identity rejects it before target submission.

## Workstation lifecycle

Lifecycle commands are behavior, not metadata. A backend may accept them only
when it preserves their standard ordering:

- create-phase commands run once for a newly constructed workstation;
- start-phase commands run once for each corresponding workstation start; and
- target execution begins only after required preparation succeeds.

A preparation receipt binds completion to the configuration fingerprint, image
identity, platform, and logical workstation. Ambiguous preparation does not
authorize an automatic replay. Backends that launch a fresh read-only container
for each target cannot claim persistent create-phase semantics merely because
the project workspace survives.

Image caches, prepared containers, native disks, and checkpoints may reduce
repeated work, but they are not project authority. Source, the selected
workstation configuration, and the project Makefile must remain sufficient to
reconstruct the result.

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
configuration containing `forwardPorts` before allocation.

Host requirements are checked on the actual machine immediately before OCI
preflight and Make. They complement backend declarations: a backend may be
declared as GPU-capable while a particular allocation has no GPU. Codespaces
is declared as a CPU workstation and rejects a required GPU configuration before a
provider rebuild. On Colab and Lightning, `gpu: true` or a CDI device request
requires `--gpu` (or a saved GPU selection) before allocation; the Dev Container
file does not silently choose a provider product or accelerator model.
`gpu: "optional"` never causes silent allocation or device injection; CDI
remains the explicit device request.

## Security and compatibility

The portable Cloudmake adapter drops capabilities, requests
`no-new-privileges`, uses a read-only image root, exposes a fresh writable
`/tmp`, and grants only the writable `/workspace` project mount plus explicitly
requested CDI device edits. A dynamically qualified Dev Container implementation follows
its standard runtime model instead; Cloudmake still rejects requests for added
privilege, but does not claim that Docker's default Dev Container boundary is
the same as the portable adapter's sandbox. Provider-native Codespaces remains
subject to metadata embedded in the selected image and is therefore a
trusted-image boundary.

Workspace persistence is independent of Dev Container execution. This contract
does not define checkpointing. Source plus the project Makefile remain the
rebuild authority; persistence behavior is documented separately in
[Day 2: workspace persistence](../tutorials/day2-workspace.md).

Workstation validation applies only at a workload boundary: `--start`, target
execution, collection, and the selected-workstation portion of `--doctor`.
Resource recovery operations such as `--status` and `--stop`, and independent
source/artifact operations such as `--sync` and `--fetch`, remain available if
a saved Dev Container becomes invalid or unsupported after an upgrade. This
prevents a compatibility failure from stranding a running or billable resource.

Run provenance records the chosen engine (`adapter` or `native`), the complete
required-capability-to-field mapping, and both backend capability ceilings.
Environment values remain excluded; only their names are recorded.

## Public compatibility corpus

Cloudmake keeps an opt-in, revision-pinned corpus of official Dev Container
samples for C++, Go, Java, Node.js, Python, and Rust, plus the official Ubuntu
template. The gate records two distinct outcomes:

- portable configurations execute a real project Make target through the local
  Docker adapter; and
- richer configurations produce explicit requirement sets which are matched to
  the local reference implementation or rejected by restricted backends.

The harness resolves the upstream image tags to recorded OCI digests but does
not remove lifecycle, build, Feature, port, or privilege requirements merely to
obtain a pass. This makes the corpus a compatibility boundary test rather than
a collection of curated trivial images. Run it explicitly with:

```sh
CLOUDMAKE_TEST_REAL_DEVCONTAINERS=1 python3 -m pytest \
  tests/compatibility/test_devcontainers.py -m real_github
```

The default suite validates the harness and pins offline; it never downloads
repositories or images.
