# Agent Discipline — gwork

Public Python CLI: sync local Markdown/CSV with Google Docs and Sheets via `gog`.
GitHub: `alvaroemur/gwork`. Local checkout may still be named `cowork-drivesync`.

Consumed as a git submodule by `secretary-core` at `plugins/gwork` (passthrough
`secretary gwork`). Keep this repo public-safe: English in product code/docs;
no personal emails, names, or absolute personal paths in committed files.

## Workflow

- **Branching:** work on thread branches from `origin/main`. Never commit on `main`.
  Prefer an isolated worktree (`git worktree add -b <scope>/<desc> <path> origin/main`).
- **Commits:** Conventional Commits in Spanish (scope = module/thread, e.g. `sync`,
  `docs`, `style`, `core`). One logical change per commit.
- **Delivery:** open a PR; do not merge without owner OK unless the owner
  explicitly asked to merge in that session.
- **Blocking:** if blocked or ambiguous, stop and ask. Do not invent Drive IDs,
  accounts, or scopes.

## Repo map

| Path | Role |
|------|------|
| `src/gwork/` | Package (`cli`, `sync/`, `style/`) |
| `.gwork.yaml` | Unified manifest (transport, `files`/`items`, style tokens) — project-local, not in this repo |
| `tests/` | Pytest suite |
| `docs/` | Architecture / design notes |
| `README.md` | User-facing install, auth, commands |

Manifest **version 2** uses `files` + nested `resources` (Doc tabs / Sheet worksheets).
Version 1 flat `items` still loads; `gwork organize --apply` migrates.

## Auth and live Drive

- Credentials come from **gog** (`gog auth login --account=<email>`).
- Default transport account is whatever `.gwork.yaml` sets under `transport.account`.
- Live Drive E2E needs a valid OAuth token. `invalid_grant` means reauth that
  account before claiming E2E passed. Prefer mocked tests for CI.

## Commands agents use most

```bash
python3 -m pytest -q
gwork --help
gwork item add --drive-id ID --type doc|sheet   # plan; add --apply to write
gwork organize [--drive-id ID]                  # plan; add --apply to write
gwork plan / gwork apply                        # content sync review-first
```

`--only` must resolve to exactly one item (path, resource id, drive id, or
`DRIVE_ID/RESOURCE_ID`). Zero or ambiguous matches fail.

## Consumer: secretary-core

After merging behavior changes that affect the CLI surface, pin
`secretary-core` `plugins/gwork` to the new `main` commit (submodule gitlink only)
in a separate PR on `secretary-core`. Verify `secretary gwork --help` and any new
passthrough (e.g. `organize`).

## Skills

Canonical agent skill: `~/.claude/skills/gwork/SKILL.md` (aliases `drive-sync`,
`gdoc-style-sync`). Update the skill when CLI or manifest semantics change.
Gemini mirror: `~/.gemini/config/skills/gwork/`.
