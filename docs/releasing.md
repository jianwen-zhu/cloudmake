# Releasing Cloudmake

Public `main` is release-oriented. Intermediate development commits stay local
or on an explicitly named development branch; stable releases are merged or
pushed to `main` only after their gates pass.

## Release gate

1. Update `VERSION` and move the matching changelog section from `Unreleased` to
   the release date.
2. Run the complete offline suite on macOS and Linux through CI.
3. Run the pinned real-GitHub project gate.
4. Run live backends affected by the release. Accelerator or transport changes
   require the live Colab CUDA gate; provider-specific changes require that
   provider's smoke test.
5. Confirm `git diff --check`, a clean working tree, and no active temporary
   compute.
6. Create an annotated `v<VERSION>` tag and push `main` plus that tag.

The release workflow verifies that the tag matches `VERSION`, reruns the offline
suite, creates a reproducible source archive with `make dist`, writes its SHA-256
checksum, and publishes both files in a GitHub release.

## Live provider gates

Run live provider gates from a maintainer workstation using the provider CLI's
existing local authentication. Cloudmake release automation must never export,
upload, reconstruct, or store provider configuration, OAuth tokens, API tokens,
or SSH keys in GitHub Actions secrets or hosted runners.

Hosted CI remains credential-free and uses provider doubles or public,
non-allocating compatibility checks. A live gate is therefore a documented local
release step, not a GitHub Actions job.
