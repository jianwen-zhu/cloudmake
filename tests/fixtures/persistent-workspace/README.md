# Persistent-workspace fixture

This deliberately small, ordinary Make project validates the format-neutral
workspace contract before Cloudmake attempts an ORFS-scale workload. Its target
names belong to this fixture; they are not Cloudmake commands.

- `provision` builds a project-local executable.
- `run` executes it and writes a result.
- `advance` atomically advances a small piece of generated state.
- `clean` removes generated state.

Everything worth preserving is project-relative. The fixture uses no
Cloudmake-specific variables or APIs and has no network or provider credentials.
