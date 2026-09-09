# Historical Kaggle course evaluation

> Kaggle is deprecated and not recommended as a Cloudmake remote-workstation
> backend. This expensive harness is retained to reproduce the technical and
> performance evidence; it no longer gates a Cloudmake release.

This historical evaluation covers two real course consumers already qualified
on local hardware and Colab. It is intentionally opt-in because it creates
private Kaggle notebook versions, consumes CPU/GPU quota, and can take many
hours. It is not a release gate.

The gate accepts three prepared project directories rather than copying course
or staff material into Cloudmake:

1. a clean extraction of the public ECE326 Lab 1 ZIP;
2. the private ECE326 paired Lab 4 calibration project; and
3. the ECE467 accelerator-labs checkout with its pinned libttl submodule.

It reproduces ECE326's accepted `setup`, public tests, real Bottle benchmark,
and paired Lab 4 calibration. It then reproduces ECE467's published Colab
onboarding sequence on the exact Kaggle accelerator name. Unlike Colab, every
target gets a fresh VM, so success also proves that the Kaggle checkpoint
preserves the project-managed home, dependencies, build products, and JIT cache.

Run locally with existing Kaggle CLI authentication:

```sh
export KAGGLE_USERNAME=your-account-slug
export CLOUDMAKE_TEST_LIVE_KAGGLE_COURSES=1
tests/acceptance/kaggle-courses/run.sh \
  /tmp/ece326-lab1 \
  /path/to/ece326-lab4-pair \
  /path/to/ece467-labs \
  /tmp/cloudmake-kaggle-course-evidence
```

The harness enables requested internet because both course bootstraps acquire
pinned external dependencies. The Kaggle account must satisfy the provider's
phone and Persona identity prerequisites; otherwise Kaggle can retain
`enable_internet=true` in notebook metadata while withholding the UI control and
job egress. Cloudmake checks reachability before Make. A job without egress
fails as infrastructure with `target_submission=not_submitted`; that is useful
historical evidence, not a reason to alter either course Makefile or replay its
target.

ECE467 runs through Kaggle's OCI/CDI profile using an immutable official
PyTorch CUDA development image. The harness passes the project's existing
`STATE_ROOT` Make variable as `$(HOME)/.cache/ece467-labs`, because ECE467's
Colab-oriented `/content/.ece467-labs` default is outside Cloudmake's managed
workspace. It also passes `LIBRARY_PATH=/usr/local/cuda/lib64/stubs`: the
official image includes NVIDIA's link-time CUDA driver stub there but correctly
does not expose it through its runtime `LD_LIBRARY_PATH`. These are ordinary
project Make variable overrides; neither course tree nor Cloudmake's OCI runner
contains an ECE467-specific workaround. Override `KAGGLE_ECE467_IMAGE` only
with another digest-pinned linux/amd64 image containing `make`, Python, a C++
compiler, complete LibTorch CUDA headers/libraries, the CUDA development
toolchain, and an equivalent link-time driver contract. See
the [historical backend report](../../../docs/historical/kaggle-notebook.md) for
the live evidence and limitations.

The harness leaves private kernel/checkpoint evidence intact on failure. Review
it and use the normal force-gated workspace purge command when it is no longer
needed.
