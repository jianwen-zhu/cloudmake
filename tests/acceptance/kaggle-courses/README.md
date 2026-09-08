# Kaggle course acceptance

This is the release gate for the two real course consumers already qualified on
local hardware and Colab. It is intentionally opt-in because it creates private
Kaggle notebook versions and consumes free CPU/GPU quota.

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
pinned external dependencies. Cloudmake checks reachability before Make. A
provider job that accepts `enable_internet=true` but has no egress fails as
infrastructure with `target_submission=not_submitted`; that is a failed release
gate, not a reason to alter either course Makefile or replay its target.

The harness leaves private kernel/checkpoint evidence intact on failure. Review
it and use the normal force-gated workspace purge command when it is no longer
needed.
