# Per-tab baselines

## Problem

Drift detection compared the Drive `modifiedTime` of the whole Doc with a
snapshot keyed by local file. Consequences:

- A tab without a snapshot always counted as drifted ("no previous snapshot").
- Any edit, or any apply on another tab, marked every tab of the Doc as drifted.
- `bootstrap` stored the local file hash and the Doc `modifiedTime`, never the
  remote content, so a local file that differed from Drive looked in sync.

## Model

`sync/baseline.py` reduces both sides to the same normalized lines:

| Line | Meaning |
|------|---------|
| `TITLE\|…`, `H1\|…`..`H6\|…` | headings |
| `LIST\|…` | list item (nesting and numbering ignored) |
| `P\|…` | paragraph |
| `T\|a\|b` | table row |

Normalization trims and collapses whitespace, straightens curly quotes, maps
non-breaking spaces and dashes, drops empty paragraphs and horizontal rules,
and ignores inline images (reported by `has_inline_objects`).

Per tab, the state is one of:

| State | Condition | Plan status |
|-------|-----------|-------------|
| `in_sync` | local lines equal remote lines | `noop` |
| `no_baseline` | differs, no baseline stored | `no_baseline` (apply skips) |
| `drift` | differs, remote hash ≠ baseline hash | `doc_drift` |
| `local_ahead` | differs, remote hash = baseline hash | `ok` |

The baseline hash is stored in `.gwork.state.json` (`baseline_hash`); the lines
are stored in `.gwork/baseline/` so the drift can be diffed later.

## Apply guards

1. Docs need `--only` or `--all`.
2. The tab is re-read; its hash must equal the one in the reviewed plan.
3. A baseline must exist and match, unless `--overwrite-remote`.
4. A tab with inline images is refused unless `--allow-image-loss`
   (`clear_body_requests` deletes the whole tab body).
5. After the write, the other registered tabs of the Doc are hashed again.

`docx_upload` items keep the legacy `modifiedTime` flow.

## Known limits

- Equality is textual and structural at paragraph level; it does not compare
  bold, colors, or fonts.
- Replacing the body is still whole-tab. Paragraph-level patching, which would
  keep images, is not implemented.
