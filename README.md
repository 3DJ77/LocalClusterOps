# CrewComms Upload Snapshot

This repository is a scrubbed upload copy of the current CrewComms codebase. It exists separately from the live repair tree so public-facing cleanup can happen without touching the working repo.

## Layout

- `CrewComms-V6/` — active LibreChat-based app snapshot prepared for upload cleanup
- `bin/` — repo-root helper wrappers for relocated tooling

## Working Rules

- Treat `CrewComms-V6/librechat.local.yaml` as the canonical local config snapshot.
- Keep internal crew naming out of release-facing labels and notes in this upload repo.
- Keep runtime and environment-specific noise out of commits unless intentionally needed.
