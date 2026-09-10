# Codespaces inbound-network acceptance

This opt-in live gate proves that a Make-provided workload in the selected
Codespaces workstation can receive a connection from outside its VM through
GitHub's authenticated port-forwarding service. Direct Internet ingress to the
VM remains blocked, and public exposure is deliberately not required.

The fixture starts a Python HTTP listener as an ordinary project target. The
harness creates a private `gh codespace ports forward` tunnel, retrieves a
per-run marker through it, stops the listener, stops the Codespace, and records
evidence for every step. It never changes port visibility to public and never
handles GitHub credentials; the official `gh` client owns authentication.

Run it against an existing temporary Cloudmake anchor Codespace:

```sh
export CODESPACE=cloudmake-network-gate-name
export CLOUDMAKE_TEST_LIVE_CODESPACES_NETWORK=1
tests/acceptance/codespaces-network/run.sh \
  /tmp/cloudmake-codespaces-network-evidence
```

The default digest-pinned Python image is the same provider-native workstation
used by the course-consumer gate. Override `CODESPACES_NETWORK_IMAGE` only with
another digest-pinned image that supplies Python 3.

This qualifies authenticated private workload ingress, not unauthenticated
public hosting. GitHub supports `private`, `org`, and `public` forwarded-port
visibility, subject to account and organization policy. Cloudmake v2.2 reports
that inbound capability as conditional. Cloudmake 2.3 additionally consumes the
standard `devcontainer.json` `forwardPorts` field as bounded private-loopback
reachability; it still does not request public visibility.
