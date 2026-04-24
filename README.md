# LocalClusterOps

This repository is a scrubbed upload snapshot for the LocalClusterOps system.
It is maintained separately from the live working tree so public-facing cleanup
and release preparation can happen without touching the operational repo.

## Layout

- Main application snapshot directory at the repository root
- `bin/` - repo-root helper wrappers for relocated tooling

## Working Rules

- Treat `librechat.local.yaml` in the application snapshot as the canonical local config.
- Keep private/internal naming out of release-facing labels and notes.
- Keep runtime and environment-specific noise out of commits unless intentionally needed.

## Release Guard

- Run `bin/release-guard.sh` before push to validate naming and tree-shape rules.
- Use `bin/release-guard.sh --allow-dirty` during local edits before commit.
