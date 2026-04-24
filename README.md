# LocalClusterOps

This repository is a scrubbed upload snapshot for the LocalClusterOps system.
It is maintained separately from the live working tree so public-facing cleanup
and release preparation can happen without touching the operational repo.

## Layout

- `CrewComms-V6/` - active LibreChat-based app snapshot prepared for release
- `bin/` - repo-root helper wrappers for relocated tooling

## Working Rules

- Treat `CrewComms-V6/librechat.local.yaml` as the canonical local config snapshot.
- Keep private/internal naming out of release-facing labels and notes.
- Keep runtime and environment-specific noise out of commits unless intentionally needed.
