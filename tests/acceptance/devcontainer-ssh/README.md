# Portable Dev Container SSH acceptance

This opt-in gate validates Cloudmake 2.3 against an actual Linux host reached by
the user-managed `ssh` backend. It uses a temporary local project and a
digest-pinned image containing Make and Python 3. It proves:

- explicit Dev Container selection and literal environment delivery;
- non-root Make execution through a dynamically qualified OCI runtime;
- generated-state reuse across targets on the remote host;
- one foreground loopback port through the Cloudmake-owned SSH tunnel; and
- normal artifact collection.

```sh
export SSH_HOST=lab-gpu
export CLOUDMAKE_DEVCONTAINER_IMAGE=REGISTRY/IMAGE@sha256:64_HEX_DIGEST
export CLOUDMAKE_TEST_LIVE_DEVCONTAINER_SSH=1
tests/acceptance/devcontainer-ssh/run.sh /tmp/cloudmake-devcontainer-evidence
```

To qualify the privilege-restricted path, prepare a host on which Docker,
Podman, and nerdctl are unavailable but `skopeo`, `umoci`, PRoot, `setpriv`,
Make, Python 3, rsync, and tar are installed. Set
`CLOUDMAKE_EXPECT_RUNTIME=proot`; the gate then requires the PRoot receipt.
Cloudmake neither installs those host prerequisites nor changes the SSH host.

The server handles one request and exits, so the foreground Make target and its
SSH tunnel end together. No public port or firewall rule is created.
