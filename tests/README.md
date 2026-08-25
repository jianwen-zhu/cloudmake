# Test suite

The default suite is deliberately offline. Provider integration tests put fake
`colab`, `kaggle`, `gh`, `ssh`, and `rsync` executables at the front of `PATH`;
they never allocate cloud compute or use account credentials.

Run everything that is implemented today:

```sh
python3 -m pip install -r requirements-test.txt
python3 -m pytest
```

If pytest is installed by a separate environment manager, invoking its `pytest`
executable directly is equivalent.

Run one layer:

```sh
python3 -m pytest tests/test_source_fingerprint.py
python3 -m pytest tests/test_resilience.py
python3 -m pytest tests/test_notebooks.py
python3 -m pytest -m integration
```

## Real GitHub CUDA projects

Cloudmake carries small Makefile overlays for two public course projects:

- NVIDIA's CUDA C++ Execution Spaces lesson gains `build`, `run`, and `clean`;
- GPU MODE's vector-addition Makefile gains a `run` target while preserving its
  existing default build.

The overlays are covered offline with fake compilers. To also sparse-clone the
pinned upstream revisions, apply the overlays, and exercise their targets:

```sh
CLOUDMAKE_TEST_REAL_GITHUB=1 python3 -m pytest \
  tests/test_real_github_projects.py -m real_github
```

This invokes `tests/real_projects/prepare.sh`, which prints the two prepared
project directories. The clones are revision-pinned so an upstream change cannot
silently alter a regression run.

The live Colab gate is intentionally more explicit because it allocates GPU
compute and uses the current Colab credentials. It clones both projects, runs the
overlaid `run` targets on separate T4 sessions, and stops each session in a
`finally` block:

```sh
CLOUDMAKE_TEST_LIVE_COLAB=1 python3 -m pytest \
  tests/test_real_github_projects.py -m live_cloud
```

`tests/contract/` exercises the public `cloudmake` launcher interface, including
configuration precedence, aliases, external project isolation, arbitrary target
dispatch, zero reserved project names, target-agnostic artifact collection,
option-only lifecycle routing, opaque project-assignment transport, and read-only
operations.

Test coverage is organized around observable behavior rather than provider SDK
internals:

- deterministic source fingerprinting and exclusions;
- archive safety and atomic Colab source replacement;
- Kaggle notebook generation, metadata, bounded status polling, and failure
  handling;
- executable Colab and Kaggle notebooks against temporary projects;
- portable Make build, test, run, package, clean, and incremental behavior;
- reproducible Makefile overlays for pinned NVIDIA and GPU MODE CUDA lessons;
- backend lifecycle and command construction through fake provider clients;
- per-backend commands, settings, Python version, authentication probes, and
  installation guidance;
- project ownership, atomic state, local and remote locks, stale recovery, and
  live-session reconciliation;
- shared source manifests, dry-run plans, ignore rules, source-size gates, and
  backend capability contracts;
- safe transactional artifact replacement and status normalization; and
- the launcher against external projects through Colab, Kaggle, and the common
  SSH transport, including lossless Make-variable passthrough without host-engine
  interpretation.
