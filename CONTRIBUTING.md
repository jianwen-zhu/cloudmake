# Contributing to Cloudmake

Cloudmake's central contract is deliberately small: an ordinary local Make
project exposes an arbitrary target, and Cloudmake runs that target remotely
without changing the project layout or reserving target names.

## Development workflow

1. Create a focused branch and keep provider credentials outside the repository.
2. Add behavior-oriented tests for every change.
3. Run `python3 -m pytest`.
4. Run the opt-in real-GitHub or live-provider gates only when the change reaches
   those boundaries; see `tests/README.md`.
5. Explain backend-contract or project-contract changes explicitly in the pull
   request. Compatibility changes require documentation and regression coverage.

The default suite must remain offline. Provider clients in ordinary integration
tests are fakes and must not allocate compute or inspect a developer's account.
Direct engine tests must use its generic `dispatch` entry point rather than add
or depend on convenience rules named after sample project targets. See the
[backend contract](docs/backend-contract.md#internal-engine-dispatch).

## Design boundaries

- Keep the local working tree as the source of truth.
- Do not require Git hosting, committed source, fixed directory names, or
  provider-specific project files.
- Keep notebook and SSH transports distinct when their lifecycle semantics differ.
- Do not retry a mutating target when the provider outcome is ambiguous.
- Treat downloaded archives and remote workspaces as untrusted inputs.

Please report security problems privately according to `SECURITY.md`.
