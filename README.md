# gwork

Sync local CSV and Markdown files with Google Drive (Sheets and Docs) through a
review-first workflow. `plan` creates a reviewable diff; `apply` executes the
approved plan.

## Installation

```
cd gwork
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Pandoc must be installed (`brew install pandoc`).

## Authentication

gwork uses the credentials managed by `gog-cli`. Authenticate the account
before running gwork:

```
gog auth login --account=user@example.com
```

## Unified manifest

Store transport, content items, and design tokens in `.gwork.yaml`:

```yaml
version: 1
transport:
  provider: gog
  account: user@example.com
items:
  - local: docs/spec.md
    drive_id: DOCUMENT_ID
    type: doc
    content_mode: ast
  - local: data/matrix.csv
    drive_id: SPREADSHEET_ID
    type: sheet
    key_column: id
style:
  document_id: DOCUMENT_ID
  template_tab: _template
  tokens: {}
```

## Usage

```
cd path/to/project
gwork sync fetch --comments --diff  # Read-only drift, comments, and approximate diff.
gwork sync plan                     # Compare local files with Drive and create
                                    # preview/ plus decisions.yaml.
# Review .gwork/preview/decisions.yaml and resolve pending cells.
gwork sync apply                    # Apply the plan to Sheets and Docs.

# Or run the full workflow with a preflight check:
gwork sync sync --apply             # fetch → plan → apply; abort if Drive
                                    # diverged from the snapshot.
```

## Docs writes: `content_mode`

Doc items support two write modes:

- `ast` (default) builds the native Doc tree with `insertText`, `insertTable`,
  and `namedStyleType`. It preserves margins, tabs, and `namedStyles`.
- `docx_upload` uploads a Pandoc `.docx` and replaces the whole file. Items with
  `protect_styling` require `--force-content-push`.

See [AST insertion](docs/ast-insertion.md) for design details and limits.

## Google Docs design system (`gwork style`)

Apply the design system declared in `.gwork.yaml` to a managed Doc:

```
gwork init --doc-id DOCUMENT_ID
                      # Extract tokens and create or refresh _template.
gwork style audit    # Refresh tokens and _template, then report drift.
gwork style audit --no-refresh-template
                      # Read-only audit against stored tokens.
gwork style plan     # Preview the batchUpdate requests.
gwork style apply    # Remove dividers, set page layout, and apply one batch.
gwork style init     # Create a Doc with seeded namedStyles.
```

Top-level `init` inspects an existing Doc. `style init` creates a new Doc and is
the only way to seed brand tokens into `HEADING_1` and other named styles. The
Docs API does not expose `updateNamedStyles`, so existing documents only support
the `apply` overlay.

## Diagrams

Open `docs/architecture.html`, or serve it with
`python3 -m http.server 8765 --directory docs/`.
