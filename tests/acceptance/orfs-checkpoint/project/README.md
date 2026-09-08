# Pinned ORFS acceptance project

This ordinary Make project is Cloudmake 2.0's live, end-to-end persistence
gate. It deliberately uses a small `nangate45/gcd` design and two consecutive
ORFS stages rather than attempting a complete chip flow during early
checkpoint validation.

- `orfs-floorplan` acquires pinned ORFS source and tools into `.orfs-state/`,
  runs `floorplan`, and records the output database's identity.
- `orfs-place` requires and verifies that recorded database before running
  `place`; it then proves the floorplan was not regenerated and writes
  `evidence/orfs-checkpoint.txt`.
- `clean` removes all generated project state.

ORFS is pinned to commit
`68cc9bc974502b4786a68e9f51a092e0fcb56e82`, its matching official image is
`openroad/orfs:26Q3-488-g68cc9bc97`, and the project-local Apptainer launcher is
pinned to 1.5.3. Apptainer/SIF is only project-owned acceptance machinery here;
it is not a Cloudmake 2.0 bundle API or managed runner.

Everything expensive or stateful is project-relative so Cloudmake's
format-neutral workspace checkpoint can preserve it. No provider credential,
registry credential, or Cloudmake secret is stored in the project.
