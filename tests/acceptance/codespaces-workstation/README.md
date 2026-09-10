# Codespaces provider-native OCI acceptance

This opt-in live gate validates the v2.2 workstation contract against an
existing Codespace created from the Cloudmake anchor repository. It consumes
Codespaces quota and performs provider rebuilds.

The gate selects a digest-pinned public OCI image, verifies unprivileged Make
execution, proves that generated project state survives ordinary targets and a
stop/start boundary, retrieves an artifact, restores the neutral anchor, and
stops the Codespace. It never clones or pushes the test project.

```sh
export CODESPACE=NAME_FROM_GH_CODESPACE_LIST
export CLOUDMAKE_CODESPACES_IMAGE=REGISTRY/IMAGE@sha256:64_HEX_DIGEST
tests/acceptance/codespaces-workstation/run.sh
```

Choose a Debian-compatible Linux image that either contains `make`, `rsync`,
and `tar`, or permits the adapter to install them with `apt-get`. The cleanup
trap attempts to restore the neutral Cloudmake anchor and stop the resource
even when an assertion fails. Confirm resource status manually after any
provider or network interruption.
