# Codespaces provider-native OCI acceptance

This opt-in live gate validates the v2.3 portable Dev Container workstation
contract against an
existing Codespace created from the Cloudmake anchor repository. It consumes
Codespaces quota and performs provider rebuilds.

The gate selects the fixture's standard Dev Container file, maps its
digest-pinned public image, literal environment, and host requirements into the
provider-native environment, verifies unprivileged Make execution, proves that
generated project state survives ordinary targets and a stop/start boundary,
retrieves an artifact, restores the neutral anchor, and stops the Codespace. It
never clones or pushes the test project.

The final `native-anchor` target intentionally does not require the Dev
Container environment; it verifies that reverting the provider to its neutral
native configuration remains usable after the portable-workstation checks.

```sh
export CODESPACE=NAME_FROM_GH_CODESPACE_LIST
tests/acceptance/codespaces-workstation/run.sh
```

The pinned fixture is a Debian-compatible Linux image and permits the adapter
to install Make, rsync, tar, and Python with `apt-get`. The cleanup trap attempts
to restore the neutral Cloudmake anchor and stop the resource even when an
assertion fails. Confirm resource status manually after any provider or network
interruption.
