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

Store transport, Drive files, nested resources, and design tokens in
`.gwork.yaml`:

```yaml
version: 2
transport:
  provider: gog
  account: user@example.com
files:
  - drive_id: DOCUMENT_ID
    type: doc
    title: Product specification
    directory: docs/product-specification
    resources:
      - id: TAB_ID
        title: Overview
        local: docs/product-specification/overview.md
        content_mode: ast
      - id: CHILD_TAB_ID
        title: Details
        parent_id: TAB_ID
        local: docs/product-specification/overview/details.md
  - drive_id: SPREADSHEET_ID
    type: sheet
    title: Metrics
    directory: sheets/metrics
    resources:
      - id: "0"
        title: Current
        local: sheets/metrics/current.csv
        key_column: id
style:
  document_id: DOCUMENT_ID
  template_tab: _template
  tokens: {}
```

Resource IDs are stable Drive IDs. Titles may change without changing the
local path. Existing version 1 `items` manifests still load. The next applied
organization plan migrates them to version 2 while preserving sync options and
unrelated manifest sections.

## Register and organize Drive files

Registration and organization are plan-only by default:

```
gwork item add --drive-id DOCUMENT_ID --type doc
gwork item add --drive-id SPREADSHEET_ID --type sheet
gwork item add --drive-id DOCUMENT_ID --type doc --apply

gwork organize
gwork organize --drive-id DOCUMENT_ID --apply
```

`item add` discovers all Doc tabs or Sheet worksheets and proposes deterministic
local paths. `organize` reconciles registered files after Drive titles or
resources change. It updates titles by stable ID, adds missing local files, and
marks removed resources as disabled. It never deletes local content or changes
Drive organization. Apply refuses to overwrite a non-empty file.

For Docs, child tabs map to nested directories. For Sheets, each worksheet maps
to one CSV under the spreadsheet directory. Name collisions receive a stable
numeric suffix.

The old flat form remains valid:

```yaml
items:
  - local: docs/spec.md
    drive_id: DOCUMENT_ID
    type: doc
    content_mode: ast
  - local: data/matrix.csv
    drive_id: SPREADSHEET_ID
    type: sheet
    key_column: id
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

Use `--only` with an exact local path, resource ID, Drive ID, or
`DRIVE_ID/RESOURCE_ID`. A Drive ID is valid only when it identifies one local
resource. Zero matches and ambiguous matches fail with a registration or
selection hint; gwork never falls back to the first manifest item.

```
gwork sync fetch --only docs/product-specification/overview.md
gwork sync sync --only DOCUMENT_ID/TAB_ID
gwork sync apply --only SPREADSHEET_ID/0
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
