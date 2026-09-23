# AST insertion: Markdown to native Google Docs

Status: implemented in `src/gwork/sync/docs_ast.py` through
`replace_doc_content_ast`.

## Problem

`update_doc_content` in [`docs.py`](../src/gwork/sync/docs.py) sends the complete
Pandoc `.docx` to:

```
PATCH https://www.googleapis.com/upload/drive/v3/files/{id}?uploadType=media
```

This operation replaces the entire file. Every push removes tabs, margins, page
layout, and document `namedStyles`, then uses Pandoc's output in their place.

The `protect_styling` guard and `--force-content-push` flag ask for human
confirmation before this destructive operation. They mitigate the wrong write
mechanism.

## Solution

Build the native document tree with `deleteContentRange`, `insertText`,
`insertTable`, and `updateParagraphStyle` requests. Assign `namedStyleType`
directly. The file remains in place, so margins, tabs, and `namedStyles` survive.
Inserted content inherits those styles.

This composes with `gwork style`. If `gwork style init` seeded the target Doc's
brand styles, inserting a paragraph with `namedStyleType: HEADING_1` applies the
existing heading style without character-level patches.

## Pipeline

```
Markdown → (pandoc -t json) → Pandoc AST → intermediate model → Docs requests
```

Pandoc provides the Markdown front end. It is already available through
`pypandoc`, and its grammar covers CommonMark and tables.

The intermediate `Paragraph`, `Run`, and `Table` model separates Markdown
grammar from the Docs API. It is a flat list of paragraphs and tables, matching
the structure of a Doc body.

### Node mapping

| Pandoc node | Docs API request |
| :--- | :--- |
| `Header n` | `insertText` + `namedStyleType: HEADING_n` |
| `Para` / `Plain` | `insertText` + `namedStyleType: NORMAL_TEXT` |
| `Strong` / `Emph` / `Strikeout` | `updateTextStyle` with `bold`, `italic`, or `strikethrough` |
| `Code` / `CodeBlock` | `updateTextStyle` with `weightedFontFamily: Courier New` |
| `Link` | `updateTextStyle` with `link: {url}` |
| `BulletList` / `OrderedList` | `createParagraphBullets` with a `BULLET_…` or `NUMBERED_…` preset |
| `BlockQuote` | `indentStart: 36pt`; `gwork style` supplies the rest of the callout |
| `Table` | `insertTable` + `insertText` per cell |
| `HorizontalRule` | Discarded because `remove_dash_dividers` removes it |
| `Image`, `Note`, `DefinitionList`, `RawBlock` | `UnsupportedNode` |

`UnsupportedNode` fails instead of silently degrading the document. The error
occurs during `plan`, not `apply`. The item receives
`status: unsupported_ast`; set `content_mode: docx_upload` for that item.

## UTF-16 index offsets

The Docs API counts positions in UTF-16 code units. A character outside the BMP
uses two units, while Python counts it as one code point. All range arithmetic
therefore uses `u16len()`. Plain `len()` would misalign every range after the
first supplementary character.

Insertion uses three phases:

1. **Insert blocks.** Insert every block at index 1 in reverse document order.
   Each insertion shifts existing content right, preserving final order without
   invalidating calculated indices. This phase uses one `batchUpdate`.
2. **Fill table cells.** `insertTable` creates empty cells. Read the document
   once, then fill cells from last to first so each source index remains valid.
3. **Apply styles.** `updateParagraphStyle`, `updateTextStyle`, and
   `updateTableCellStyle` do not change text length, so one document read
   supplies every index. Run `createParagraphBullets` last because it can remove
   existing list markers.

Total: three batches and two document reads.

### Match the model to the document

Phases 2 and 3 must match each model block to a document element. Docs inserts
empty paragraphs around some elements, including tables. `match_blocks` scans
content, skips unrelated elements, and compares paragraph text. It raises
`RuntimeError` when no block matches instead of writing to the wrong indices.

## Tables

Pandoc emits `TableHead`, `TableBody`, and `TableFoot` separately. The model
flattens them into rows with the header first. `insertTable` requires a
rectangular grid, so merged cells with `rowspan` or `colspan` other than 1 raise
`UnsupportedNode`.

This module does not set column widths or zebra striping. Docs creates tables as
`EVENLY_DISTRIBUTED`; `gwork style apply` sets usable widths through the
`auto_restore_table_widths` guard.

## Links

`link_mode` runs in the Markdown transform layer before AST conversion:

- `preserve` keeps Markdown links and converts them to native Doc links through
  `textStyle.link`.
- `rewrite_to_drive` runs `rewrite_links` to replace relative targets with
  manifest-defined Drive URLs.

Links added directly in the Doc are still removed because `sync_mode: replace`
replaces the body. The `_doc_remote_drift` guard protects that case.

## Tab-scoped replacement

`Item.doc_tab` selects the destination tab. When set:

- `gog docs raw --tab=<id>` returns indices local to that tab.
- Every request includes `tabId` in its `range` or `location`.

Without `doc_tab`, operations target the default tab. `clear_body_requests`
preserves the body's required final paragraph by deleting from index 1 through
`endIndex - 1`.

## Retiring `--force-content-push`

The flag existed because the only write path was destructive. AST insertion
removes that need in three steps:

1. `content_mode` defaults to `ast`. The destructive path requires
   `content_mode: docx_upload`. `protect_styling` blocks only that path, while
   AST items proceed. The flag remains accepted with a deprecation warning.
2. After active manifests migrate, using `--force-content-push` with
   `content_mode: ast` becomes an error.
3. Remove the flag and `update_doc_content`. Keep `protect_styling` as an intent
   marker without a gate.

While `docx_upload` exists, `--force-content-push` remains the only gate for
whole-file replacement.

## Known limits

- Hard `LineBreak` nodes become spaces. Inserting `\n` would create a paragraph
  and misalign the model.
- Nested lists use `indentStart` proportional to depth, not native
  `createParagraphBullets` levels.
- Images, footnotes, and definition lists are unsupported.
- Docs leaves an empty paragraph before each inserted table. This is cosmetic;
  `gwork style` does not treat it as a divider.
