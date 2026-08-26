# cloudmake

**License:** [Apache License 2.0](LICENSE)

`cloudmake` brings the familiar local Make workflow to the accelerator cloud.
Modern GPUs and other accelerators are expensive and fast-moving, while their
most accessible cloud services are fragmented across notebooks, batch jobs, and
quota-backed development environments. Cloudmake makes a locally executable,
Make-based project work on that hardware—including free-tier services—without
modifying the project. The developer keeps editing and controlling the source
locally while Cloudmake adapts each provider around it.

The intended daily interface is deliberately close to Make:

```sh
cd my-project
cloudmake --use colab --gpu=T4  # once for this project
# These three target names are defined by my-project/Makefile, not cloudmake.
cloudmake compile
cloudmake verify
cloudmake --collect dist export-release
```

The project remains the source of truth. `cloudmake` invokes targets from the
project's normal `Makefile`; remote backends transfer the local working tree and
retrieve selected output around that invocation.
Provider notebooks, transfer logic, session metadata, and generated control files
belong to the cloudmake tool, not to the project.

> [!IMPORTANT]
> The seven documented backends and the external-project `cloudmake` launcher are
> implemented. The regression suite uses offline provider doubles; configure and
> verify your own account with `cloudmake --doctor` before allocating compute.

## Objective

Modern accelerators such as GPUs are expensive, evolve quickly, and are often
outside the practical reach of individual developers. Buying hardware also means
committing to one generation while compilers, drivers, architectures, and
performance characteristics continue to change.

General-purpose CPU cloud has largely converged on familiar Linux VMs,
containers, SSH, and mature infrastructure tooling. The accelerator cloud has
not. GPU type and availability vary; drivers, runtimes, compilers, and hardware
generations are tightly coupled; and the affordable entry points are often
provider-specific notebook sessions, immutable batch jobs, or quota-backed
studios rather than ordinary long-lived machines.

Services such as Colab, Kaggle, and Lightning make accelerator hardware
available free of charge or within limited quotas, but each exposes a different
development lifecycle. One executes notebooks in a reusable session, another
submits fresh batch versions, and another offers a persistent filesystem over
SSH while switching machines. These interfaces break the local
edit-build-test-run loop precisely where developers need to compare and adopt
rapidly changing hardware. CPU services such as Codespaces remain useful as a
portable SSH reference and cross-build surface, but generic CPU cloud is not the
primary problem Cloudmake is designed to solve.

Access to compute should not require moving the source of truth into a provider's
Git service. Cloud development tools often assume that the remote machine will
clone a hosted repository, coupling compute access to repository hosting,
credentials, and provider-specific setup. Notebook templates, special project
files, prescribed directory layouts, and cloud-specific Make targets move even
more provider machinery into the project. The cost is not merely setup time: it
fragments the project's normal local workflow.

Cloudmake is therefore not another general cloud provisioning layer. Its focus
is the awkward boundary between an ordinary local Make project and accessible
accelerator hardware. The desired behavior is simple: make that project work on
the accelerator cloud unmodified. Cloudmake treats the local working tree,
including uncommitted changes and local-only projects, as the source of truth
and adapts each provider around it.

Intrusion-free is a product boundary, not merely a convenience. Cloudmake does
not require provider files, provider-specific Makefiles, fixed target names, a
prescribed source layout, injected Make variables, a Git remote, or committed
source. It adapts itself to the project and keeps provider machinery in the tool.

“Unmodified” describes this integration boundary: cloudmake preserves the
project's Make interface and layout. The selected cloud image must still provide
the toolchain and runtime dependencies that the project itself requires.

```text
local Make project, unmodified
    |
    v
cloudmake: accelerator-cloud adapter for arbitrary project targets
    |
    +-- direct Make ----------> local reference execution
    |
    +-- native notebook API --> Colab or Kaggle
    |
    `-- SSH + rsync ----------> provider sessions or an existing SSH host
                                  |
                                  v
                         evolving GPU/accelerator hardware
```

The design has seven goals:

1. Broaden practical access to modern, rapidly changing accelerators rather
   than duplicate generic cloud infrastructure tooling.
2. Keep adoption intrusion-free: an existing Make project should run unchanged.
3. Preserve the familiar local edit-and-Make workflow; keep the common cloud
   invocation as small as `cloudmake TARGET`.
4. Use plain Make as the common remote execution contract, without reserving
   target names or injecting variables.
5. Keep the local working tree as the source of truth, independent of repository
   hosting and commit state.
6. Preserve backend-specific capabilities through cloudmake options and explicit
   user configuration, never through implicit project requirements.
7. Support reusable sessions, batch notebooks, and SSH VMs without pretending
   that their lifecycles are identical.

## What Cloudmake does not do

Cloudmake is deliberately a narrow host-side dispatcher and transfer layer
around a project's existing Make interface. Three principles govern that
boundary:

1. **Preserve project intent.** Cloudmake adapts itself to the project; it does
   not redefine the project's targets, layout, dependencies, source authority,
   or output semantics.
2. **Preserve backend intent.** Cloudmake does not change the intended
   capability of backend VMs or runtimes. It uses provider-supported execution,
   lifecycle, persistence, and access surfaces as they actually exist. It does
   not turn a notebook into an SSH VM, a batch job into persistent compute, a
   runtime image into a development image, or free-tier access into paid-tier
   entitlement.
3. **Coordinate rather than replace.** Cloudmake synchronizes source, dispatches
   Make, and retrieves selected output. It does not absorb the responsibilities
   of build systems, source control, secrets managers, infrastructure
   provisioners, schedulers, IDEs, or deployment platforms.

The detailed exclusions follow from those principles:

| Cloudmake does not | Responsibility remains with |
| --- | --- |
| Provision generic cloud infrastructure, networks, storage systems, or clusters | Cloud providers and established infrastructure tools. |
| Change the intended capability of a backend VM or runtime | The provider's supported image, lifecycle, access method, persistence model, quota, and entitlement remain authoritative. |
| Define `build`, `test`, `run`, or any other project target | The project's Makefile. Every positional target is project-provided. |
| Replace Make or interpret the project's recipes and variables | The project and its chosen build tools. |
| Prescribe source, build, output, or dependency directory layouts | The project. Cloudmake preserves relative paths. |
| Install compilers, CUDA toolchains, libraries, or project dependencies | The selected cloud image or the project's own setup rules. Cloudmake checks only its documented execution prerequisites. |
| Clone, commit, push, or otherwise manage project source control | The developer. The local working tree, including uncommitted files, remains authoritative. |
| Manage provider credentials or act as a secrets manager | Official provider clients and the developer's secret-management mechanism. Selected project files are transferred, so secrets must be excluded from source synchronization. |
| Decide which project output is an artifact | The project chooses and populates a directory; `--collect` only retrieves the explicitly selected directory. |
| Erase differences between reusable sessions, batch jobs, and SSH VMs | Each backend retains its real lifecycle and exposes it consistently through Cloudmake operations. |
| Guarantee free compute, a particular accelerator, runtime duration, persistence, capacity, or price | The cloud provider's current policy, quota, image, and availability. |
| Automatically retry an ambiguously completed project target | The developer must first determine whether the original execution produced side effects. |
| Provide a full remote IDE, job scheduler, or deployment platform | Existing provider interfaces and purpose-built tools. Cloudmake supplies only the documented execution, shell, browser, and artifact surfaces. |

These exclusions are design boundaries rather than missing implicit behavior.
New backends should adapt providers to the same small project contract instead
of changing provider capabilities or expanding Cloudmake into any of these
roles.

## Design

### Tool repository and project repository are separate

Cloudmake is installed once as a stable tool:

```text
cloudmake/
|-- bin/cloudmake
|-- Makefile
|-- VERSION
|-- core/
|-- backends/
|-- host-templates/
|-- transports/
|-- notebooks/
|-- tools/
|-- tests/
|-- .devcontainer/
`-- Makefile.build
```

An actual project needs only an ordinary Makefile at its root. Everything else
may use any layout:

```text
my-project/
|-- Makefile       # the only required path
`-- ...            # sources, scripts, data, and subdirectories in any layout
```

Cloudmake synchronizes the whole selected project tree while preserving relative
paths. Its remote workspace happens to call the synchronized root `src`, but
that is an internal location and does not require a local `src/` directory.

No provider notebook, Gist ID, Git remote, `Makefile.colab`, or
`Makefile.codespaces` is required in the project. A project may opt into a shared
cloudmake configuration later, but the zero-configuration layout remains the
default.

The cloudmake repository also acts as the neutral GitHub Codespaces anchor. A
Codespace checks out the tool repository only to provision a suitable VM. The
actual project is uploaded from the local computer to a separate workspace and
is never cloned from GitHub by cloudmake.

### Incremental source synchronization

Cloudmake treats transfer time and bandwidth as part of the development loop,
not as an unavoidable full upload before every Make invocation. A common source
manifest gives every remote backend the same selected tree, exclusions,
fingerprint, and change preview. Run `cloudmake --sync-dry-run` on a remote
backend to see added, modified, and deleted paths without authenticating to or
contacting a provider. The local backend reports that no transfer is selected.

The transport then uses the strongest incremental behavior its provider surface
can support:

- The local backend transfers nothing. It invokes the working tree's Makefile
  directly, so the project's existing dependency graph and outputs are already
  available without a synchronization boundary.
- SSH backends use `rsync`, transferring changed source while deleting stale
  synchronized paths from the remote project workspace.
- A reusable Colab session compares the source fingerprint and skips the source
  archive upload entirely when the selected tree is unchanged. When it changes,
  Colab receives a complete validated snapshot because its native file API does
  not expose an rsync-like delta transport.
- Kaggle starts a fresh batch VM for every submitted target, so remote
  incremental synchronization is impossible. Cloudmake still reuses the local
  compressed snapshot when the source is unchanged, then submits that snapshot
  with the new job.

Source transfer is only the first layer of incrementality. On a reusable
session, Cloudmake invokes successive project-provided targets in the same
remote workspace. Prior outputs that remain in that workspace are therefore
visible to the project's Make dependency graph, which—not Cloudmake—decides
which recipes are already up to date and which must run again. A fresh batch VM
has no previous remote outputs and cannot provide this incremental Make
behavior.

This is deliberately transport-aware: Cloudmake optimizes repeated operations
without pretending that notebook APIs, batch jobs, and SSH offer identical
persistence. Source selection, safety checks, and recovery behavior are
described in [Resilience and recovery](docs/resilience.md).

### Intrusion-free Make contract

Cloudmake invokes an arbitrary target from the project's Makefile. It has no
fixed mandatory target names. The concise rules below are specified fully in
the [project contract](docs/project-contract.md):

| Project contract | Requirement |
| --- | --- |
| Root `Makefile` | Mandatory for every project-target invocation. |
| The target named in `cloudmake TARGET` | Must exist or be resolvable by that Makefile. |
| The target named in `cloudmake --collect DIR TARGET` | Has ordinary Make semantics; after success cloudmake collects project-relative `DIR`. |
| Local `src/`, `build/`, or `output/` directories | Not required. |
| Root `.git/`, `.cloud-state/`, and `artifacts/` | Reserved from source synchronization as metadata, tool state, and downloaded output. |

Cloudmake injects no Make variables. The remote invocation contains the exact
target plus only user-supplied `NAME=value` assignments. For
`--collect DIR TARGET`, the project chooses the project-relative directory and
populates it through its normal rules. After success, cloudmake creates or
transactionally replaces the local `artifacts/` directory with those contents.

### Launcher and engine boundary

The `cloudmake` executable is a thin launcher. It discovers the project, resolves
the selected backend, and loads local preferences. Remote operations delegate to
cloudmake's Make-based engine; the local backend deliberately bypasses that
engine and invokes the project Makefile directly. The launcher does not become a
second build system.

Local execution is the reference semantics:

```sh
cloudmake -b local benchmark SIZE=large
# Equivalent project invocation:
make -f Makefile benchmark SIZE=large
```

There is no source scan, archive, synchronization, session, remote workspace, or
backend-variable injection on that path. A remote backend must preserve the same
target and user-supplied assignments while adding only the transfer and lifecycle
machinery its provider requires. Cloudmake still records local provenance, and
`--collect DIR TARGET` still materializes the selected directory safely into the
Cloudmake-owned `artifacts/` destination.

Every positional name is passed through to the project:

```sh
# clean, benchmark, and test are targets defined by the project's Makefile.
cloudmake clean
cloudmake benchmark SIZE=large
cloudmake -j 8 test
```

Cloudmake reserves no project target names. Even names that resemble its own
operations are unconditionally project targets:

```sh
# These invoke hypothetical project-provided targets named fetch and status.
cloudmake fetch
cloudmake status
```

Cloudmake's own operations use options instead: `cloudmake --fetch` and
`cloudmake --status`. Target names are encoded while crossing the transport, so
spaces, quotes, and other Make-compatible punctuation remain data rather than
shell syntax.

Backend settings remain available through Cloudmake options or the host
environment. They never share the trailing project-assignment namespace:

```sh
KAGGLE_TIMEOUT=7200 cloudmake -b kaggle PROJECT_TARGET
COLAB_IDENTITY=/path/to/key cloudmake -b colab-ssh --shell
```

Here and throughout this README, `PROJECT_TARGET` is a placeholder for a target
provided by the selected project's Makefile. It is not a target supplied by
Cloudmake.

### State and credentials

Generated state does not belong in either Git repository. The launcher keeps
per-project preferences, fingerprints, generated notebooks, archives, SSH
configuration, and downloaded provider output under the user's configuration,
state, and cache directories. Project identity is derived from the absolute local
path.

Cloudmake owns the project's local `artifacts/` directory. A successful
`--collect DIR TARGET` creates or transactionally replaces it with the selected
remote directory; the project does not need to create the local destination.

Configuration precedence is:

```text
command line
  > environment variables
  > per-project local preferences
  > optional shared project configuration
  > global user preferences
  > backend defaults
```

The `--host` selection is deliberately local-only: command line and environment
values precede per-project and global user preferences, while repository-shared
configuration cannot select a user's OpenSSH alias.

Cloudmake does not store provider passwords, OAuth tokens, personal access tokens,
or SSH private keys. Authentication remains owned by the `colab`, `kaggle`,
`gh`, and `lightning` clients or by the user's existing OpenSSH configuration
for a selected host. Source archives and private notebook versions must not be
treated as secret storage. See the
[security model](docs/security.md) for the complete trust boundary.

### Backend naming

Short names are for people; canonical names describe the transport unambiguously:

| User-facing name | Canonical backend | Transport |
| --- | --- | --- |
| `local` | `local` | Direct project Make invocation |
| `colab` | `colab-notebook` | Native Colab contents and kernel APIs |
| `kaggle` | `kaggle-notebook` | Private Kaggle notebook version |
| `codespaces` | `codespaces-ssh` | SSH and rsync |
| `colab-ssh` | `colab-ssh` | SSH and rsync |
| `ssh` | `host-ssh` | User-managed SSH and rsync |
| `lightning` | `lightning-studio-ssh` | SSH and rsync |

`colab` always means native notebook access. It never silently changes to SSH.

## Onboarding

### 1. Install common host tools

Cloudmake targets macOS and Linux. The common host needs:

- POSIX-compatible shell
- GNU Make or a compatible Make implementation
- `tar`
- Python 3 for the current notebook helpers
- One provider CLI where the selected backend requires one
- OpenSSH and `rsync` only for SSH backends

The remote environment needs Make and whatever compiler, runtime, libraries, and
drivers the project itself requires.

### 2. Install cloudmake

Install the launcher from the tool checkout:

```sh
git clone <cloudmake-repository-url>
cd cloudmake
make install
cloudmake --version
```

Installation creates an unprivileged launcher under `~/.local/bin/cloudmake`
and installs its self-contained runtime under `~/.local/libexec/cloudmake/`.
Add `~/.local/bin` to `PATH` if necessary. Before installation, the same
interface is available as `./bin/cloudmake` from the tool checkout.

### 3. Check provider readiness

The readiness checks are read-only:

```sh
cloudmake --doctor
cloudmake --backends
```

`cloudmake --backends` reports the adapters and whether their main host clients are
installed. `cloudmake --doctor` checks the selected backend's complete local
prerequisites and provider authentication without allocating a VM. It also
prints the installed client version and the client line used for Cloudmake's
latest compatibility validation.

The checker has two levels:

- `prerequisites` validates required local commands, the Python version where
  applicable, backend settings, and readable local files. Every operational
  target is gated by this check.
- `doctor` runs `prerequisites`, then performs a read-only provider probe for
  authentication and access. It never creates, starts, submits, or stops compute.
  Compute and transfer targets pass through this probe before provider work.

Backend maintainers can invoke the same engine gates directly:

```sh
make BACKEND=colab-notebook prerequisites
make BACKEND=colab-notebook doctor
```

Failures identify the missing command or setting and print the backend-specific
installation/authentication hint before any compute operation is attempted.

### 4. Select a backend

Selection is a local preference stored outside the project:

```sh
cloudmake --use colab --gpu=T4
```

Other examples:

```sh
cloudmake --use local
cloudmake --use kaggle
cloudmake --use codespaces
cloudmake --use ssh --host lab-gpu
cloudmake --use colab --global
```

Use `-b` for a one-off override without changing the saved preference:

```sh
# verify is a target defined by this project's Makefile.
cloudmake -b kaggle verify
```

### 5. Run the project

```sh
# compile, verify, and export-release are project-provided Make targets.
cloudmake compile
cloudmake verify
cloudmake --collect dist export-release
cloudmake --history
```

The names in this example belong entirely to the project; any other target works
the same way. Compute commands start or reuse the required environment
automatically. `--collect` changes artifact handling, not the meaning of its
target.
Typing `cloudmake` without a command is read-only: it shows the current project,
selected backend, and concise help. Use `cloudmake --status` when a live provider
status probe is wanted.

## Usage

The intended command form is:

```text
cloudmake [options] TARGET [NAME=value ...]
```

There are no reserved positional commands: `TARGET` always belongs to the
project. Cloudmake operations are option-only. In examples, `PROJECT_TARGET`
means “replace this with a target provided by your project's Makefile”; Cloudmake
does not define a target with that name.

Common options:

| Option | Meaning |
| --- | --- |
| `-b`, `--backend NAME` | Use one backend for this invocation. |
| `-C DIR` | Treat `DIR` as the local project directory. |
| `-j N` | Pass the parallel job count to Make. |
| `--host HOST` | Select a user-managed OpenSSH alias for the `ssh` backend. |
| `--gpu`, `--gpu=TYPE` | Request the default or a named GPU where supported. |
| `--cpu` | Explicitly request a CPU runtime. |
| `--verbose` | Show provider and transfer commands. |

Cloud operation options:

| Option | Behavior |
| --- | --- |
| `--use BACKEND` | Save the backend and applicable host or accelerator preference. |
| `--start` | Allocate or wake a reusable backend when applicable. |
| `--sync` | Synchronize source without running a project target. |
| `--sync-dry-run` | Preview source changes without contacting the provider. |
| `--status` | Show provider and session/job status. |
| `--fetch` | Retrieve the latest prepared output. |
| `--collect DIR TARGET` | Run any project target, collect project-relative `DIR`, and fetch it. |
| `--open` | Open the provider's notebook or browser interface. |
| `--shell` | Open an interactive shell on SSH backends. |
| `--stop` | Stop or release reusable compute. |
| `--doctor` | Check local tools and authentication without allocation. |
| `--backends` | List backends and local client availability. |
| `--host-templates` | List bundled OpenSSH alias templates. |
| `--host-template NAME` | Print one bundled alias template without modifying SSH configuration. |

Examples:

```sh
# Work on a project without changing directory; compile is defined by ../solver/Makefile.
cloudmake -C ../solver compile

# Use Kaggle for a project-provided verify target and request its exact accelerator.
cloudmake -b kaggle --gpu=NvidiaL4 verify

# Pass settings to the project-provided benchmark target.
cloudmake benchmark DATASET=small DEBUG=1

# Open a real remote terminal where the backend permits SSH.
cloudmake -b codespaces --shell

# Run a project-provided benchmark target on any existing SSH host.
cloudmake -b ssh --host lab-gpu benchmark

# Explicitly release a reusable Colab session.
cloudmake -b colab --stop
```

## Backend prerequisites

### Local backend

Use `local` as the zero-transfer reference backend or as a persistent local
preference while developing without cloud compute:

```sh
cloudmake --use local
cloudmake --doctor
# benchmark is supplied by the project's Makefile.
cloudmake benchmark SIZE=small
```

It requires only a readable root `Makefile` and GNU Make or a compatible Make
implementation. Project targets run directly in the selected project directory.
`--start`, `--sync`, `--sync-dry-run`, `--status`, and `--stop` report their local
no-op or readiness semantics; there is no provider interface, separate shell, or fetch operation.
Use `--collect DIR TARGET` when a uniform `artifacts/` materialization is useful
locally as well as remotely.

### Colab native notebook backend

Use this as the normal Colab backend. It uses the official Colab CLI's contents
and kernel APIs rather than SSH, Git, or a Gist.

Prerequisites:

1. A Google account with access to Colab.
2. macOS or Linux. The official CLI currently does not support Windows.
3. The official [`google-colab-cli`](https://github.com/googlecolab/google-colab-cli):

   ```sh
   uv tool install google-colab-cli
   # or
   python3 -m pip install google-colab-cli
   ```

4. Complete the CLI's Google authorization flow on first use, then verify it:

   ```sh
   colab version
   colab sessions
   ```

Cloudmake uses `colab new`, `sessions`, `upload`, `download`, `exec`, `url`, and
`stop`. The source is fingerprinted before upload. An unchanged tree reuses the
remote source and persistent build directory in the named session.

Colab kernel execution defaults to a 3600-second cloudmake timeout rather than
the CLI's short interactive default. Override it for longer workloads with, for
example, `COLAB_TIMEOUT=7200 cloudmake PROJECT_TARGET`, replacing
`PROJECT_TARGET` with a target from the project's Makefile.

Accelerator availability, runtime duration, and usage limits are dynamic and are
not guaranteed. Omitting the GPU requests a CPU runtime. Always stop an unused
session:

```sh
cloudmake -b colab --stop
```

The CLI keeps its own authentication and session information in the user's Colab
CLI configuration; cloudmake does not copy those tokens.

### Kaggle notebook backend

Kaggle is a private batch-notebook backend. Every project-target submission
creates a notebook version and runs in a fresh VM. There is no reusable
interactive session.

Prerequisites:

1. A Kaggle account with notebook access and any required phone/account
   verification for accelerators.
2. Python 3.11 or newer for the current Kaggle CLI.
3. The official [`kaggle` CLI](https://github.com/Kaggle/kaggle-cli):

   ```sh
   uv tool install kaggle
   kaggle auth login
   kaggle --version
   ```

4. Your Kaggle account slug, supplied through the environment or command line:

   ```sh
   export KAGGLE_USERNAME=your-account-slug
   ```

Cloudmake generates a private notebook in its local state, embeds the compressed
source snapshot, submits it with `kaggle kernels push`, waits for completion, and
downloads logs or artifacts through the notebook-output API. The project does not
need a GitHub repository or Gist.

Although the generated notebook is private, its versions retain uploaded source
in the Kaggle account's version history. Do not include credentials, private keys,
or other secrets in the source tree. Internet access is disabled by default.

#### Preinstalled Kaggle GPU stack

As of 2026-08-25, Kaggle's official GPU image is built from a pinned Colab GPU
runtime. Its image definition preserves the base image's `torch`, `tensorflow`,
`keras`, and `jax` packages, then installs Kaggle's additional environment and
GPU-specific PyCUDA package. The official image tests exercise the following
GPU surfaces:

| Preinstalled surface | Official GPU-image coverage | Natural batch use |
| --- | --- | --- |
| PyTorch and its Lightning, Ignite, vision, audio, metrics, and tuning ecosystem | CUDA tensors, linear algebra, and recurrent neural-network modules | Training, inference, and framework-managed compilation |
| TensorFlow and Keras | CUDA build, GPU discovery, matrix operations, and model execution | Training and inference |
| JAX and Flax | JAX selects its GPU backend | XLA/JIT workloads |
| CuPy | A custom `ElementwiseKernel` executes on the GPU | NumPy-like GPU code and runtime-compiled kernels |
| Numba | A `numba.cuda.jit` kernel executes on the GPU | Python-authored CUDA JIT kernels |
| PyCUDA | CUDA driver initialization and device discovery | Driver-level Python integration; source compilation is not guaranteed |
| RAPIDS cuDF and cuML | GPU dataframe operations and PCA | Batch dataframe and machine-learning workloads |

Some official tests, including the current cuDF and cuML checks, are exempted on
P100 machines. Package presence therefore does not guarantee that every surface
works on every accelerator Kaggle may offer.

Sources: Kaggle's official
[`Dockerfile.tmpl`](https://github.com/Kaggle/docker-python/blob/main/Dockerfile.tmpl),
[`kaggle_requirements.txt`](https://github.com/Kaggle/docker-python/blob/main/kaggle_requirements.txt),
and [GPU image tests](https://github.com/Kaggle/docker-python/tree/main/tests).

This is an image snapshot, not a permanent Cloudmake guarantee. Kaggle rebuilds
and updates the environment independently. In particular, its image definition
does not install or test `nvcc`, so native CUDA C++ compilation must not assume
that the standalone CUDA compiler is present. Kaggle is therefore best treated
as a framework/JIT or compatible-prebuilt-binary execution backend. The project
should expose its own target for that work; Cloudmake defines no Kaggle-specific
project target.

Kaggle accelerator names are provider-specific. Use the exact identifier exposed
by the installed CLI, for example:

```sh
# PROJECT_TARGET must be provided by the project's Makefile.
cloudmake -b kaggle --gpu=NvidiaTeslaT4 PROJECT_TARGET
```

`start` only verifies authentication, and `stop` is a no-op because Kaggle ends
the batch VM automatically.

### GitHub Codespaces SSH backend

Codespaces is the standard SSH backend for included-quota or paid CPU VMs. The
cloudmake repository is the neutral anchor repository; the actual project is
uploaded from the local working tree to `/workspaces/.cloudmake/` and is not
cloned from GitHub.

Prerequisites:

1. A GitHub account with Codespaces access and available included quota or a
   configured billing method.
2. The official [GitHub CLI](https://cli.github.com/).
3. GitHub CLI authentication with Codespaces permission:

   ```sh
   gh auth login
   gh auth refresh -h github.com -s codespace
   gh auth status
   ```

4. A Codespace created from the cloudmake anchor repository:

   ```sh
   gh codespace create -r OWNER/cloudmake
   gh codespace list
   ```

5. A working SSH server in the dev container, plus `rsync`, Make, and the desired
   toolchain. The cloudmake anchor will provide these. GitHub's default dev
   container already starts an SSH server; custom images can add the
   `ghcr.io/devcontainers/features/sshd:1` feature. See GitHub's
   [Codespaces CLI guide](https://docs.github.com/en/codespaces/developing-in-a-codespace/using-github-codespaces-with-github-cli).

Verify the connection independently before using cloudmake:

```sh
gh codespace ssh -c CODESPACE-NAME
```

Select an existing Codespace by name:

```sh
export CODESPACE=CODESPACE-NAME
```

Source synchronization uses rsync over the SSH configuration produced by
`gh codespace ssh --config`. Cloudmake never commits or pushes the uploaded
project. Stop the Codespace when it is not in use because active and retained
Codespaces consume account quota according to GitHub's current policy.

### Colab SSH backend

This is an explicit paid-tier backend, not a fallback for `colab`. It provides a
conventional SSH and rsync surface through the Colab CLI's WebSocket proxy.

Prerequisites:

1. All prerequisites for the native Colab backend.
2. A paid Colab plan and positive compute-unit balance. Google's
   [Colab FAQ](https://research.google.com/colaboratory/faq.html) lists remote
   control such as SSH among the activities restricted on free managed runtimes
   without a positive balance.
3. Local OpenSSH, rsync, and an Ed25519 or ECDSA key pair.
4. A supported private key, discovered automatically or selected explicitly:

   ```sh
   COLAB_IDENTITY=/path/to/id_ed25519 cloudmake -b colab-ssh --shell
   ```

The runtime may continue consuming compute units while it remains active. Stop it
explicitly after use:

```sh
cloudmake -b colab-ssh --stop
```

Google's current CLI documents `colab ssh`, but access policy and billing remain
provider-controlled and can change independently of cloudmake.

The Colab SSH doctor can verify the local client, key, and Colab authentication,
but it cannot prove paid SSH entitlement or positive compute balance without
attempting a runtime connection. That final check therefore occurs only when an
operational SSH command is requested.

### User-managed SSH host backend

Use `ssh` when the remote machine already exists and you can reach it through
OpenSSH—for example, a university lab server, an organization workstation, an
Oracle or Google free-tier VM, or a rented CPU or GPU machine. Cloudmake treats
that machine as an execution surface only. It never provisions, configures,
starts, stops, or changes the hardware or software capabilities of the host.

Prerequisites:

1. Local OpenSSH, `rsync`, and Python 3.
2. Remote Make, `rsync`, and `tar`, plus the compiler, runtime, libraries, and
   drivers required by the project.
3. A simple OpenSSH `Host` alias in `~/.ssh/config`. Put the username, key,
   jump host, port, and other connection details there rather than in Cloudmake:

   ```sshconfig
   Host lab-gpu
       HostName gpu42.example.edu
       User researcher
       IdentityFile ~/.ssh/id_ed25519
       ProxyJump lab-gateway
   ```

Verify that alias independently, then select it for Cloudmake:

```sh
ssh lab-gpu true
cloudmake -b ssh --host lab-gpu --doctor
cloudmake --use ssh --host lab-gpu
# PROJECT_TARGET must be provided by the project's Makefile.
cloudmake PROJECT_TARGET
```

The saved host is a local per-project preference outside the project tree. A
one-off `--host` switches machines without replacing it:

```sh
cloudmake --host oci-free PROJECT_TARGET
```

`SSH_HOST=lab-gpu` is also accepted as an environment override, but `--host` is
the clearer interactive surface. A repository's `.cloudmake.json` cannot choose
an SSH host because aliases and trust decisions belong to the local user.

Cloudmake installs editable alias templates for a generic Linux host, OCI Always
Free, and a Google Compute Engine free-tier `e2-micro`. List or render them from
either the source checkout or an installed launcher:

```sh
cloudmake --host-templates
cloudmake --host-template generic
cloudmake --host-template oci-always-free
cloudmake --host-template gcp-e2-micro
```

Rendering writes only to standard output. Cloudmake never edits `~/.ssh/config`
or creates a key; the user reviews, edits, and installs a fragment explicitly.
See the bundled [SSH host template guide](host-templates/README.md) for the safe
copy, `Include`, permission, and first-connection workflow.

Source is synchronized incrementally under `.cloudmake/` in the configured
remote user's login home. `--start` validates the existing connection,
`--status` checks reachability, and `--stop` deliberately reports a no-op because
the machine is user-managed. `--gpu` is not accepted: Cloudmake uses whatever
hardware the selected host already provides and does not alter it.

Cloudmake passes only the selected `SSH_HOST` alias to `ssh` and `rsync`. It
neither reads nor copies SSH keys, agents, certificates, or configuration into
project or tool state. Authentication, host verification, jump-host policy, and
key management remain entirely under OpenSSH and the host administrator or cloud
provider.

### Lightning Studio SSH backend

Lightning Studios provide a persistent development filesystem with CPU and GPU
machine switching. Cloudmake uses the provider's normal SSH surface, so source
updates remain incremental and build outputs survive stop/start cycles. The
actual project still comes from the local working tree; cloudmake does not clone
it from GitHub. Remote project state lives under the provider-documented
persistent Studio home at `/teamspace/studios/this_studio/.cloudmake/`.

Prerequisites:

1. A [Lightning AI account](https://lightning.ai/docs/overview/ai-studio/)
   with Studio access and available credits or quota.
   New accounts may need to finish provider onboarding or verification before
   Studio creation is authorized.
2. The official Lightning SDK/CLI:

   ```sh
   uv tool install lightning-sdk
   lightning login
   lightning auth whoami
   ```

3. A teamspace slug in `OWNER/TEAMSPACE` form and a stable Studio name:

   ```sh
   export LIGHTNING_TEAMSPACE=your-owner/general
   export LIGHTNING_STUDIO=cloudmake-dev
   ```

4. Provider-managed SSH setup. Create or start the Studio once, then let the
   Lightning client establish its own key and SSH entry:

   ```sh
   lightning studio start --name "$LIGHTNING_STUDIO" \
     --teamspace "$LIGHTNING_TEAMSPACE" --machine CPU --create
   lightning ssh configure --name "$LIGHTNING_STUDIO" \
     --teamspace "$LIGHTNING_TEAMSPACE"
   ```

   This creates the provider-owned key at `~/.ssh/lightning_rsa`. Cloudmake
   references that key but never copies it into project, tool, or generated
   source state. Set `LIGHTNING_IDENTITY` only if the provider key is at another
   readable path.

Verify the read-only gate and select the backend:

```sh
cloudmake -b lightning --doctor
cloudmake --use lightning --gpu=T4
# Replace PROJECT_TARGET with a target provided by the project's Makefile.
cloudmake PROJECT_TARGET
```

With no `--gpu`, the backend uses Lightning's 4-CPU `CPU` machine. Accelerator
values are Lightning machine names such as `T4`, `L4`, or `A100`; availability
and cost remain provider-controlled. Each operation starts or reuses the named
Studio on the selected machine. `--stop` releases compute while retaining the
[Studio filesystem and environment](https://lightning.ai/docs/overview/ai-studio/environment-persistence)
and incremental build cache:

```sh
cloudmake -b lightning --stop
```

`--doctor` verifies the installed client, local login, teamspace visibility,
settings, and readable provider SSH key without allocating compute. A provider
eligibility, credit, or capacity failure can only be proven when `--start` or a
project target requests a machine.

## Backend behavior summary

| Backend | VM lifecycle | Source transfer | Execution | Interactive shell |
| --- | --- | --- | --- | --- |
| `local` | No VM or session | None | Direct project Make | Use the existing local shell |
| `colab-notebook` | Reusable named session | Fingerprinted archive via Colab API | `colab exec` notebook | No |
| `kaggle-notebook` | Fresh batch VM per target | Source embedded in private notebook | Kaggle kernel version | No |
| `codespaces-ssh` | Reusable quota-backed VM | Incremental rsync over SSH | Remote Make | Yes |
| `colab-ssh` | Reusable paid Colab VM | Incremental rsync over SSH | Remote Make | Yes |
| `host-ssh` | Existing user-managed host | Incremental rsync over SSH | Remote Make | Yes |
| `lightning-studio-ssh` | Persistent quota/credit-backed Studio | Incremental rsync over SSH | Remote Make | Yes |

The backends intentionally converge at the project Makefile, not at their
transport or lifecycle layer. Project developers should use the
[project contract](docs/project-contract.md); backend authors and maintainers can
find the adapter interface and extension checklist in the
[backend contract](docs/backend-contract.md).

The local backend is the no-transfer reference path. The Colab backend reuses a
live session and skips source upload when the fingerprint is unchanged. The
Kaggle backend reuses its local compressed snapshot when unchanged but still
submits a fresh VM for every target. All SSH backends share the same rsync and
remote-Make transport.

## Reliability and security

Cloudmake protects reusable workspaces with ownership checks, serializes
concurrent operations, validates remote prerequisites, and updates source and
artifacts transactionally. Intentional reassignment of a remote workspace
requires the conspicuous one-time override:

```sh
# PROJECT_TARGET is a target provided by the project's Makefile.
CLOUDMAKE_ADOPT=1 cloudmake PROJECT_TARGET
```

Use `.cloudmakeignore` for source that should never be transferred:

```text
datasets/
*.trace
local-secrets.json
```

Only the root `.git/`, `.cloud-state/`, and `artifacts/` paths are excluded
automatically. Cloudmake does not infer that names such as `build/`, `.venv/`,
`src/`, or `*_output.ipynb` are disposable; exclude them explicitly when that is
correct for the project.

Before transfer, Cloudmake refuses unmistakable private-key blocks and GitHub
access-token forms. Credential-like filenames produce a warning. Exclude such
files with `.cloudmakeignore`; for a deliberate test fixture, the conspicuous
one-command override is `CLOUDMAKE_ALLOW_SECRETS=1 cloudmake TARGET`.

`cloudmake --sync-dry-run` reports added, modified, and deleted paths without
authenticating, allocating compute, or contacting the provider. Read
[Resilience and recovery](docs/resilience.md) before adopting a workspace,
adjusting source limits, or recovering an interrupted operation.

The launcher keeps state and cache data in user directories outside both
repositories. Downloaded project output is extracted under the actual project's
`artifacts/` directory. Artifact archives are bounded by configurable
member-count, total-size, per-file-size, compressed-size, and expansion-ratio
limits before extraction.

Every project execution creates a private local provenance record containing the
backend, remote resource, target, source fingerprint, result, and—when collected—
an artifact fingerprint. Make-assignment names are recorded, but their values are
stored only as hashes. `cloudmake --history` shows the ten latest runs.

Cloudmake verifies workspace ownership before destructive synchronization,
serializes concurrent mutations, reconciles saved sessions with live provider
state, and stages source and artifact replacement so validation failures preserve
the previous valid tree. Operational commands check both host and remote
prerequisites before running project code.

The source tree is still uploaded to and executed by the selected provider.
Cloudmake keeps provider credentials in their official clients, but a private
notebook or ignored filename is not a secrets manager. Review these focused
documents before using private source or diagnosing a failure:

- [Resilience and recovery](docs/resilience.md)
- [Security model](docs/security.md)
- [Project contract](docs/project-contract.md)
- [Backend contract](docs/backend-contract.md)
- [Security reporting](SECURITY.md)
- [Contributing](CONTRIBUTING.md)
- [Release process](docs/releasing.md)

## Testing

The default test suite is offline by design. It never connects to a cloud
account or allocates compute. Integration tests place fake `colab`, `kaggle`,
`gh`, `lightning`, `ssh`, and `rsync` executables at the front of `PATH`, then
exercise the real Makefiles, transports, notebooks, and Python helpers against
temporary projects.

Install the test dependency and run the suite:

```sh
python3 -m pip install -r requirements-test.txt
python3 -m pytest
```

The suite covers portable Make behavior, all seven backends, source selection,
provider lifecycle and failures, prerequisites, ownership, locks, status
normalization, and transactional source and artifact handling. Fake-provider
tests also assert architecture boundaries such as no SSH in the native Colab
flow and no Git clone or push in the Codespaces flow.

An opt-in real-project gate sparse-clones pinned NVIDIA CUDA C++ and GPU MODE
lessons, installs regression-only Makefile overlays, and exercises them without
vendoring either repository. Explicitly enabled live gates run both overlays on
Colab or Lightning T4 sessions. See [`tests/README.md`](tests/README.md) for the
commands and allocation warning.

GitHub Actions runs only credential-free automation: the offline suite on Linux
and macOS, syntax and notebook checks, and weekly pinned-upstream CUDA project
tests that do not allocate cloud compute. Live provider gates run only from a
locally authenticated host. Stable version tags produce checksummed source
releases only after the offline suite passes again.

`tests/contract/` exercises the public launcher behavior. It specifies backend
aliases, configuration precedence, external project state, `-C`, arbitrary
targets, option-only lifecycle operations, Make-variable passthrough, read-only invocation,
and failure behavior. See [`tests/README.md`](tests/README.md) for focused test
commands.

## Project status

The existing local, Colab notebook, Kaggle notebook, Codespaces SSH, paid Colab
SSH, user-managed host SSH, and Lightning Studio SSH backends implement the documented
launcher, external-project, arbitrary-target,
incremental synchronization, artifact retrieval, prerequisite, ownership,
locking, and recovery contracts. `--collect DIR TARGET` performs target-agnostic
remote export and safe artifact retrieval as one operation; `--fetch` can
retrieve the latest prepared output again.

Provider quotas, accelerator availability, images, authentication policies, and
billing remain external constraints. Future providers should be added as new
backends against the [backend contract](docs/backend-contract.md), without
changing the project Make surface.

## License

Cloudmake is licensed under the [Apache License 2.0](LICENSE).
