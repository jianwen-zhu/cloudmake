# cloudmake

`cloudmake` makes modern cloud hardware feel like a familiar local build target.
Its primary objective is to make a locally executable, Make-based project work
on accessible cloud hardware—including free-tier services—unmodified. The
developer continues to edit and control the source locally while cloudmake
adapts provider-specific execution around it. Adopting cloudmake must not require
the project to become a cloudmake project.

The intended daily interface is deliberately close to Make:

```sh
cd my-project
cloudmake --use colab --gpu=T4  # once for this project
cloudmake compile
cloudmake verify
cloudmake --collect dist export-release
```

The project remains the source of truth. `cloudmake` transfers the local working
tree, invokes targets from the project's normal `Makefile`, and retrieves output.
Provider notebooks, transfer logic, session metadata, and generated control files
belong to the cloudmake tool, not to the project.

> [!IMPORTANT]
> The four documented backends and the external-project `cloudmake` launcher are
> implemented. The regression suite uses offline provider doubles; configure and
> verify your own account with `cloudmake --doctor` before allocating compute.

## Objective

Modern accelerators such as GPUs are expensive, evolve quickly, and are often
outside the practical reach of individual developers. Buying hardware also means
committing to one generation while compilers, drivers, architectures, and
performance characteristics continue to change.

At the same time, services such as Colab and Kaggle make some CPU, GPU, and other
accelerated compute available free of charge or within limited quotas. Additional
services such as Codespaces provide useful quota-backed development VMs. The
opportunity is real, but their usage models are fragmented: one provider executes
notebooks in a reusable session, another submits immutable batch versions, and
another exposes a conventional SSH machine. These workflows differ from the
edit-build-test-run loop that developers already understand locally.

Access to compute should not require moving the source of truth into a provider's
Git service. Cloud development tools often assume that the remote machine will
clone a hosted repository, coupling compute access to repository hosting,
credentials, and provider-specific setup. Notebook templates, special project
files, prescribed directory layouts, and cloud-specific Make targets move even
more provider machinery into the project. The cost is not merely setup time: it
fragments the project's normal local workflow.

Cloudmake's desired behavior is therefore simple: make a locally executable,
Make-based project work on accessible cloud hardware—including free-tier
services—unmodified. Cloudmake treats the local working tree, including
uncommitted changes and local-only projects, as the source of truth and adapts
each provider around it.

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
cloudmake: arbitrary project targets
    |
    +-- native notebook API --> Colab or Kaggle
    |
    `-- SSH + rsync ----------> Codespaces or paid Colab
                                  |
                                  v
                         evolving CPU/GPU hardware
```

The design has seven goals:

1. Broaden practical access to modern, rapidly changing compute hardware.
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

Cloudmake is not a replacement for Make, a source-control system, a secrets
manager, or a promise that cloud VMs are persistent. It is a host-side dispatcher
and transfer layer around a project's existing Make targets.

## Design

### Tool repository and project repository are separate

Cloudmake is installed once as a stable tool:

```text
cloudmake/
|-- bin/cloudmake
|-- Makefile
|-- core/
|-- backends/
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

### Launcher, engine, and escape hatch

The `cloudmake` executable is a thin launcher. It discovers the project, resolves
the selected backend, loads local preferences, and delegates to cloudmake's own
Make-based engine. It does not become a second build system.

Every positional name is passed through to the project:

```sh
cloudmake clean
cloudmake benchmark SIZE=large
cloudmake -j 8 test
```

Cloudmake reserves no project target names. Even names that resemble its own
operations are unconditionally project targets:

```sh
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
KAGGLE_TIMEOUT=7200 cloudmake -b kaggle build
COLAB_IDENTITY=/path/to/key cloudmake -b colab-ssh --shell
```

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

Cloudmake does not store provider passwords, OAuth tokens, personal access tokens,
or SSH private keys. Authentication remains owned by the `colab`, `kaggle`, and
`gh` clients. Source archives and private notebook versions must not be treated as
secret storage. See the [security model](docs/security.md) for the complete trust
boundary.

### Backend naming

Short names are for people; canonical names describe the transport unambiguously:

| User-facing name | Canonical backend | Transport |
| --- | --- | --- |
| `colab` | `colab-notebook` | Native Colab contents and kernel APIs |
| `kaggle` | `kaggle-notebook` | Private Kaggle notebook version |
| `codespaces` | `codespaces-ssh` | SSH and rsync |
| `colab-ssh` | `colab-ssh` | SSH and rsync |

`colab` always means native notebook access. It never silently changes to SSH.

## Onboarding

### 1. Install common host tools

Cloudmake targets macOS and Linux. The common host needs:

- POSIX-compatible shell
- GNU Make or a compatible Make implementation
- `tar`
- Python 3 for the current notebook helpers
- One provider CLI from the backend sections below
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

Installation creates an unprivileged launcher under
`~/.local/bin/cloudmake`. Add that directory to `PATH` if necessary. Before
installation, the same interface is available as `./bin/cloudmake` from the
tool checkout.

### 3. Check provider readiness

The readiness checks are read-only:

```sh
cloudmake --doctor
cloudmake --backends
```

`cloudmake --backends` reports the adapters and whether their main host clients are
installed. `cloudmake --doctor` checks the selected backend's complete local
prerequisites and provider authentication without allocating a VM.

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
cloudmake --use kaggle
cloudmake --use codespaces
cloudmake --use colab --global
```

Use `-b` for a one-off override without changing the saved preference:

```sh
cloudmake -b kaggle test
```

### 5. Run the project

```sh
cloudmake compile
cloudmake verify
cloudmake --collect dist export-release
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
project. Cloudmake operations are option-only.

Common options:

| Option | Meaning |
| --- | --- |
| `-b`, `--backend NAME` | Use one backend for this invocation. |
| `-C DIR` | Treat `DIR` as the local project directory. |
| `-j N` | Pass the parallel job count to Make. |
| `--gpu`, `--gpu=TYPE` | Request the default or a named GPU where supported. |
| `--cpu` | Explicitly request a CPU runtime. |
| `--verbose` | Show provider and transfer commands. |

Cloud operation options:

| Option | Behavior |
| --- | --- |
| `--use BACKEND` | Save the backend and accelerator preference. |
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

Examples:

```sh
# Work on a project without changing directory.
cloudmake -C ../solver build

# Temporarily use Kaggle and request its exact accelerator identifier.
cloudmake -b kaggle --gpu=NvidiaL4 test

# Pass ordinary project settings through to Make.
cloudmake run DATASET=small DEBUG=1

# Open a real remote terminal where the backend permits SSH.
cloudmake -b codespaces --shell

# Explicitly release a reusable Colab session.
cloudmake -b colab --stop
```

## Backend prerequisites

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
example, `COLAB_TIMEOUT=7200 cloudmake build`.

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

Kaggle accelerator names are provider-specific. Use the exact identifier exposed
by the installed CLI, for example:

```sh
cloudmake -b kaggle --gpu=NvidiaTeslaT4 build
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

## Backend behavior summary

| Backend | VM lifecycle | Source transfer | Execution | Interactive shell |
| --- | --- | --- | --- | --- |
| `colab-notebook` | Reusable named session | Fingerprinted archive via Colab API | `colab exec` notebook | No |
| `kaggle-notebook` | Fresh batch VM per target | Source embedded in private notebook | Kaggle kernel version | No |
| `codespaces-ssh` | Reusable quota-backed VM | Incremental rsync over SSH | Remote Make | Yes |
| `colab-ssh` | Reusable paid Colab VM | Incremental rsync over SSH | Remote Make | Yes |

The backends intentionally converge at the project Makefile, not at their
transport or lifecycle layer. Project developers should use the
[project contract](docs/project-contract.md); backend authors and maintainers can
find the adapter interface and extension checklist in the
[backend contract](docs/backend-contract.md).

## Direct engine use

The launcher is the normal project interface. Maintainers can also exercise the
Make engine directly from this tool checkout against the included sample project,
whose portable rules are in `Makefile.build`.

Colab native notebook backend, which is currently the default:

```sh
make prerequisites
make doctor
make sync-dry-run
make build
make test
make run
make REMOTE_TARGET=package REMOTE_COLLECT_DIR_B64=b3V0cHV0 collect
make open
make stop
```

Kaggle batch notebook backend:

```sh
make BACKEND=kaggle-notebook KAGGLE_USERNAME=your-account-slug build
make BACKEND=kaggle-notebook KAGGLE_USERNAME=your-account-slug \
  REMOTE_TARGET=package REMOTE_COLLECT_DIR_B64=b3V0cHV0 collect
```

Codespaces SSH backend:

```sh
make BACKEND=codespaces-ssh CODESPACE=CODESPACE-NAME build
make BACKEND=codespaces-ssh CODESPACE=CODESPACE-NAME \
  REMOTE_TARGET=package REMOTE_COLLECT_DIR_B64=b3V0cHV0 collect
make BACKEND=codespaces-ssh CODESPACE=CODESPACE-NAME stop
```

Colab paid SSH backend:

```sh
make BACKEND=colab-ssh build
make BACKEND=colab-ssh REMOTE_TARGET=package \
  REMOTE_COLLECT_DIR_B64=b3V0cHV0 collect
make BACKEND=colab-ssh stop
```

The Colab backend reuses a live session and skips source upload when the
fingerprint is unchanged. The Kaggle backend reuses its local compressed snapshot
when unchanged but still submits a fresh VM for every target. Both SSH backends
share the same rsync and remote-Make transport.

Cloudmake protects reusable workspaces with ownership checks, serializes
concurrent operations, validates remote prerequisites, and updates source and
artifacts transactionally. Intentional reassignment of a remote workspace
requires the conspicuous one-time override:

```sh
CLOUDMAKE_ADOPT=1 cloudmake build
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

`make sync-dry-run` reports added, modified, and deleted paths without
authenticating, allocating compute, or contacting the provider. Read
[Resilience and recovery](docs/resilience.md) before adopting a workspace,
adjusting source limits, or recovering an interrupted operation.

Direct engine state lives under `.cloud-state/`. The launcher instead keeps state
and cache data in user directories outside both repositories. Downloaded project
output is extracted under the actual project's `artifacts/` directory.

## Reliability and security

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

## Testing

The default test suite is offline by design. It never connects to a cloud
account or allocates compute. Integration tests place fake `colab`, `kaggle`,
`gh`, `ssh`, and `rsync` executables at the front of `PATH`, then exercise the
real Makefiles, transports, notebooks, and Python helpers against temporary
projects.

Install the test dependency and run the suite:

```sh
python3 -m pip install -r requirements-test.txt
python3 -m pytest
```

The suite covers portable Make behavior, all four transports, source selection,
provider lifecycle and failures, prerequisites, ownership, locks, status
normalization, and transactional source and artifact handling. Fake-provider
tests also assert architecture boundaries such as no SSH in the native Colab
flow and no Git clone or push in the Codespaces flow.

An opt-in real-project gate sparse-clones pinned NVIDIA CUDA C++ and GPU MODE
lessons, installs regression-only Makefile overlays, and exercises them without
vendoring either repository. A second, explicitly enabled gate runs both
overlays on temporary Colab T4 sessions. See [`tests/README.md`](tests/README.md)
for the commands and allocation warning.

`tests/contract/` exercises the public launcher behavior. It specifies backend
aliases, configuration precedence, external project state, `-C`, arbitrary
targets, option-only lifecycle operations, Make-variable passthrough, read-only invocation,
and failure behavior. See [`tests/README.md`](tests/README.md) for focused test
commands.

## Project status

The existing Colab notebook, Kaggle notebook, Codespaces SSH, and paid Colab SSH
backends implement the documented launcher, external-project, arbitrary-target,
incremental synchronization, artifact retrieval, prerequisite, ownership,
locking, and recovery contracts. `--collect DIR TARGET` performs target-agnostic
remote export and safe artifact retrieval as one operation; `--fetch` can
retrieve the latest prepared output again.

Provider quotas, accelerator availability, images, authentication policies, and
billing remain external constraints. Future providers should be added as new
backends against the [backend contract](docs/backend-contract.md), without
changing the project Make surface.
