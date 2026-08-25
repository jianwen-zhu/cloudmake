# Security model

Cloudmake is a source-transfer and remote-execution tool. It reduces accidental
credential coupling, but it does not turn a cloud VM, private notebook, or
unlisted URL into trusted secret storage.

## Trust boundaries

The selected local source is uploaded to a third-party provider or a
user-selected SSH host and executed there. Review the environment's retention,
privacy, access, billing, and acceptable-use policies before using non-public
source or data. Stopping compute does not
necessarily delete notebook history, VM storage, logs, output, or account
metadata.

Provider output is untrusted input when it returns to the host. Cloudmake
validates artifact archive members and replaces the local artifact directory
transactionally, but users must still treat produced executables and data as
code and content generated in a remote environment.

## Credentials

Authentication remains owned by the official provider clients:

- the Colab CLI owns Google authorization and session credentials;
- the Kaggle CLI owns Kaggle authentication;
- the GitHub CLI and OpenSSH own Codespaces authentication and keys;
- OpenSSH owns user-managed host aliases, authentication, keys, agents,
  certificates, host verification, and jump-host configuration; and
- the Lightning CLI and OpenSSH own Studio authentication and keys.

Cloudmake does not store provider passwords, OAuth tokens, personal access
tokens, or SSH private keys. It does not forward GitHub credentials merely to
build a project.

This boundary also applies to Cloudmake's own automation. Hosted CI must never
receive a copy of a maintainer's provider configuration or credentials. Live
provider regressions run only from an already authenticated local host; hosted
CI uses credential-free provider doubles and public compatibility checks.

The Codespaces anchor checkout and uploaded project are separate. The anchor
repository provisions a VM; cloudmake does not use its repository token to
clone, commit, or push the actual project.

For `host-ssh`, Cloudmake passes the locally selected `SSH_HOST` alias to the
local `ssh` and `rsync` clients. It does not generate SSH configuration, copy
an identity, or administer the selected machine. Access policy and machine
lifecycle remain with the user and host administrator or cloud provider. The
host alias may be saved in local user preferences, but repository-shared
configuration cannot select it.

Bundled host templates are inert examples. Cloudmake can list or print them, but
does not install a fragment into `~/.ssh`, replace existing configuration, set
host-key policy, or generate a key. Users must review and install a fragment
themselves.

## Source hygiene

Never put credentials, private keys, API tokens, build secrets, or sensitive
datasets in synchronized source. Use `.cloudmakeignore` to exclude local files
that never belong on a provider:

```text
.env
keys/
private-data/
```

This is a convenience boundary, not a secrets manager. Review the effective
selection with `cloudmake --sync-dry-run` before the first upload and after changing
exclusions.

Cloudmake scans selected regular files before packaging. It refuses unmistakable
private-key blocks and GitHub access-token forms and warns about common
credential-like filenames. The scan is intentionally conservative and cannot
identify every secret. An intentional fixture can use `CLOUDMAKE_ALLOW_SECRETS=1`
for one command; this does not make the destination safe or prevent provider
retention.

A private provider notebook, unlisted Gist, archive URL, or hard-to-guess
identifier still grants access through an account or possession of a link. None
should be used as a credential store.

If a remote build legitimately requires a secret, inject it through a
provider-supported secret facility at execution time. Do not place it in the
source tree, Make command line, generated notebook, project configuration, or
downloaded logs.

## Workspace provenance

Reusable workspaces contain an owner record derived from the canonical local
project path and host. This is diagnostic provenance used to prevent accidental
workspace reuse before destructive synchronization. It contains no provider
credential, but it reveals that local path and hostname to the selected remote
workspace or private notebook.

Intentional ownership changes require `CLOUDMAKE_ADOPT=1`. Verify the old owner
before adoption; the control protects against mistakes, not against a malicious
user who already controls the same cloud account and workspace.

## Archive and filesystem safety

Source and artifact archives reject absolute paths, traversal outside the
destination, unsafe symbolic or hard links, and special files. Source replacement
and artifact retrieval use staging directories so failed validation preserves
the prior valid tree.

Artifact extraction also enforces member-count, expanded-size, individual-file,
compressed-archive, and expansion-ratio limits. They default respectively to
50,000 files, 2 GiB total, 1 GiB per file, 1 GiB compressed, and 500:1. Advanced
users can set `ARTIFACT_MAX_FILES`, `ARTIFACT_MAX_MB`,
`ARTIFACT_MAX_FILE_MB`, `ARTIFACT_MAX_ARCHIVE_MB`, and `ARTIFACT_MAX_RATIO` in
the host environment.

Source symbolic links may not escape the local project. SSH synchronization
checks remote ownership before allowing `rsync --delete`. These controls protect
filesystem boundaries during normal operation; they do not sandbox arbitrary
commands in a project's Makefile.

## Execution and supply chain

Cloudmake invokes the project's Makefile and therefore grants its recipes the
permissions of the selected cloud account and remote VM. Review an unfamiliar
project before running it. The same applies to compilers, package managers,
downloaded dependencies, container images, and provider base images used by a
build.

Pin important dependencies where reproducibility matters. Do not assume that a
free notebook runtime, accelerator driver, or preinstalled package set remains
stable between sessions.

## Reporting a security issue

Follow the private reporting process in [`SECURITY.md`](../SECURITY.md). Do not
include live credentials, private source, or provider tokens in a public issue or
test fixture. A useful report includes the backend, lifecycle step, sanitized
provider response, expected boundary, and a minimal reproduction using dummy
files or fake-provider tests.
