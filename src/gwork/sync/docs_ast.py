from __future__ import annotations

"""Convert Markdown to `documents.batchUpdate` requests without DOCX.

The legacy path (`update_doc_content`) sends the entire DOCX through
`PATCH files/{id}?uploadType=media`. It replaces the file rather than merely
losing styles, destroying tabs, margins, and `namedStyles` on every push.
This module builds the native document tree with `insertText`, `insertTable`,
and direct `namedStyleType` assignment. Existing Doc styles remain, and
inserted content inherits them.

See `docs/ast-insertion.md` for phases, index arithmetic, tables, and links.
"""

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

HEADING_BY_LEVEL = {
    1: "HEADING_1", 2: "HEADING_2", 3: "HEADING_3",
    4: "HEADING_4", 5: "HEADING_5", 6: "HEADING_6",
}

BULLET_PRESET = {
    "bullet": "BULLET_DISC_CIRCLE_SQUARE",
    "number": "NUMBERED_DECIMAL_ALPHA_ROMAN",
}

QUOTE_INDENT_PT = 36.0
NESTING_INDENT_PT = 18.0
CODE_FONT = "Courier New"


class UnsupportedNode(Exception):
    """An AST node has no faithful Docs API translation.

    Fail explicitly instead of silently degrading the document. Callers can
    use the DOCX path with `content_mode: docx_upload`.
    """


def u16len(text: str) -> int:
    """Return the UTF-16 length used for Docs API indexes.

    Emoji and other non-BMP characters occupy two units.
    """
    return len(text.encode("utf-16-le")) // 2


# =====================================================================
#  Intermediate model
# =====================================================================

@dataclass
class Run:
    text: str
    bold: bool = False
    italic: bool = False
    strikethrough: bool = False
    code: bool = False
    link: Optional[str] = None

    def merges_with(self, other: "Run") -> bool:
        return (
            self.bold == other.bold
            and self.italic == other.italic
            and self.strikethrough == other.strikethrough
            and self.code == other.code
            and self.link == other.link
        )


@dataclass
class Paragraph:
    runs: list = field(default_factory=list)
    named_style: str = "NORMAL_TEXT"
    bullet: Optional[str] = None       # "bullet" | "number"
    nesting: int = 0
    quote: bool = False
    code: bool = False

    @property
    def text(self) -> str:
        return "".join(r.text for r in self.runs)


@dataclass
class Table:
    rows: list = field(default_factory=list)   # list[list[list[Paragraph]]]

    @property
    def num_rows(self) -> int:
        return len(self.rows)

    @property
    def num_cols(self) -> int:
        return max((len(r) for r in self.rows), default=0)


# =====================================================================
#  Pandoc AST → model
# =====================================================================

def markdown_to_pandoc_ast(text: str) -> dict:
    result = subprocess.run(
        ["pandoc", "-f", "markdown", "-t", "json"],
        input=text, capture_output=True, text=True, check=True,
    )
    return json.loads(result.stdout)


def markdown_file_to_blocks(path: Path) -> list:
    return pandoc_ast_to_blocks(markdown_to_pandoc_ast(Path(path).read_text(encoding="utf-8")))


def markdown_to_blocks(text: str) -> list:
    return pandoc_ast_to_blocks(markdown_to_pandoc_ast(text))


def pandoc_ast_to_blocks(ast: dict) -> list:
    blocks: list = []
    meta_title = _meta_title(ast.get("meta", {}))
    if meta_title:
        blocks.append(Paragraph(runs=[Run(text=meta_title)], named_style="TITLE"))
    for node in ast.get("blocks", []):
        blocks.extend(_convert_block(node))
    return blocks


def _meta_title(meta: dict) -> str:
    node = meta.get("title")
    if not node:
        return ""
    return "".join(r.text for r in _inlines(node.get("c", []))).strip()


def _convert_block(node: dict, nesting: int = 0, quote: bool = False) -> list:
    kind = node.get("t")
    payload = node.get("c")

    if kind in ("Para", "Plain"):
        return [Paragraph(runs=_inlines(payload), nesting=nesting, quote=quote)]

    if kind == "Header":
        level, _attr, inlines = payload
        return [Paragraph(
            runs=_inlines(inlines),
            named_style=HEADING_BY_LEVEL.get(level, "HEADING_6"),
            nesting=nesting,
        )]

    if kind == "CodeBlock":
        _attr, text = payload
        return [
            Paragraph(runs=[Run(text=line, code=True)], code=True, nesting=nesting)
            for line in text.rstrip("\n").split("\n")
        ]

    if kind == "BlockQuote":
        out: list = []
        for child in payload:
            out.extend(_convert_block(child, nesting=nesting, quote=True))
        return out

    if kind == "BulletList":
        return _convert_list(payload, "bullet", nesting, quote)

    if kind == "OrderedList":
        _attrs, items = payload
        return _convert_list(items, "number", nesting, quote)

    if kind == "Div":
        _attr, children = payload
        out = []
        for child in children:
            out.extend(_convert_block(child, nesting=nesting, quote=quote))
        return out

    if kind == "HorizontalRule":
        # Drop separators because `gwork style` removes them by design.
        return []

    if kind == "Table":
        return [_convert_table(payload)]

    raise UnsupportedNode(
        f"Markdown block '{kind}' has no Docs API translation. "
        f"Use content_mode: docx_upload for this item."
    )


def _convert_list(items: list, bullet: str, nesting: int, quote: bool) -> list:
    out: list = []
    for item in items:
        first = True
        for child in item:
            converted = _convert_block(child, nesting=nesting + (0 if first else 1), quote=quote)
            for para in converted:
                if isinstance(para, Paragraph) and first:
                    para.bullet = bullet
                    first = False
                elif isinstance(para, Paragraph) and para.bullet is None:
                    para.nesting = max(para.nesting, nesting + 1)
            out.extend(converted)
    return out


def _convert_table(payload: list) -> Table:
    _attr, _caption, _colspecs, head, bodies, foot = payload
    rows: list = []
    rows.extend(_rows(head[1]))
    for body in bodies:
        rows.extend(_rows(body[2]))
        rows.extend(_rows(body[3]))
    rows.extend(_rows(foot[1]))
    return Table(rows=rows)


def _rows(raw_rows: list) -> list:
    out = []
    for row in raw_rows:
        cells = []
        for cell in row[1]:
            _cattr, _align, rowspan, colspan, blocks = cell
            if rowspan != 1 or colspan != 1:
                raise UnsupportedNode(
                    "Merged cells (rowspan/colspan) cannot be inserted through the AST."
                )
            paragraphs: list = []
            for block in blocks:
                for converted in _convert_block(block):
                    if not isinstance(converted, Paragraph):
                        raise UnsupportedNode("A cell contains a nested table.")
                    paragraphs.append(converted)
            cells.append(paragraphs or [Paragraph()])
        out.append(cells)
    return out


# =====================================================================
#  Inlines
# =====================================================================

def _inlines(nodes: list, **style) -> list:
    runs: list = []
    for node in nodes:
        runs.extend(_inline(node, **style))
    return _merge_runs(runs)


def _inline(node: dict, **style) -> list:
    kind = node.get("t")
    payload = node.get("c")

    if kind == "Str":
        return [Run(text=payload, **style)]
    if kind == "Space":
        return [Run(text=" ", **style)]
    if kind in ("SoftBreak", "LineBreak"):
        # Flatten a hard break to a space. Inserting "\n" would start a new
        # paragraph and misalign the model with the document.
        return [Run(text=" ", **style)]
    if kind == "Emph":
        return _inlines(payload, **dict(style, italic=True))
    if kind == "Strong":
        return _inlines(payload, **dict(style, bold=True))
    if kind == "Strikeout":
        return _inlines(payload, **dict(style, strikethrough=True))
    if kind in ("Underline", "SmallCaps", "Span"):
        children = payload[1] if kind == "Span" else payload
        return _inlines(children, **style)
    if kind == "Code":
        _attr, text = payload
        return [Run(text=text, **dict(style, code=True))]
    if kind == "Link":
        _attr, children, target = payload
        return _inlines(children, **dict(style, link=target[0]))
    if kind == "Quoted":
        quote_type = payload[0].get("t")
        open_q, close_q = ("“", "”") if quote_type == "DoubleQuote" else ("‘", "’")
        inner = _inlines(payload[1], **style)
        return [Run(text=open_q, **style)] + inner + [Run(text=close_q, **style)]

    raise UnsupportedNode(
        f"Markdown inline '{kind}' has no Docs API translation. "
        f"Use content_mode: docx_upload for this item."
    )


def _merge_runs(runs: list) -> list:
    merged: list = []
    for run in runs:
        if merged and merged[-1].merges_with(run):
            merged[-1].text += run.text
        else:
            merged.append(run)
    return [r for r in merged if r.text]


# =====================================================================
#  Model → batchUpdate requests
# =====================================================================

def _location(tab_id: Optional[str], index: int) -> dict:
    loc = {"index": index}
    if tab_id:
        loc["tabId"] = tab_id
    return loc


def _range(tab_id: Optional[str], start: int, end: int) -> dict:
    rng = {"startIndex": start, "endIndex": end}
    if tab_id:
        rng["tabId"] = tab_id
    return rng


def segment_blocks(blocks: list) -> list:
    """Split the document into ordered text and table segments."""
    segments: list = []
    buffer: list = []
    for block in blocks:
        if isinstance(block, Table):
            if buffer:
                segments.append(("text", buffer))
                buffer = []
            segments.append(("table", block))
        else:
            buffer.append(block)
    if buffer:
        segments.append(("text", buffer))
    return segments


def segment_text(paragraphs: list) -> str:
    return "".join(p.text + "\n" for p in paragraphs)


def clear_body_requests(tab_raw: dict, tab_id: Optional[str] = None) -> list:
    """Clear the tab body while preserving the required final paragraph."""
    content = (tab_raw.get("body", {}) or {}).get("content", []) or []
    end = max((el.get("endIndex", 1) for el in content), default=1)
    if end <= 2:
        return []
    return [{"deleteContentRange": {"range": _range(tab_id, 1, end - 1)}}]


def insert_requests(blocks: list, tab_id: Optional[str] = None,
                    index: int = 1) -> list:
    """Phase 1: insert text and empty tables.

    Insert everything at the same index in reverse document order. Each insert
    shifts existing content right, preserving final order without invalidating
    calculated indexes during the batch.
    """
    requests: list = []
    for kind, payload in reversed(segment_blocks(blocks)):
        if kind == "text":
            text = segment_text(payload)
            if text:
                requests.append({
                    "insertText": {"location": _location(tab_id, index), "text": text}
                })
        else:
            requests.append({
                "insertTable": {
                    "location": _location(tab_id, index),
                    "rows": payload.num_rows,
                    "columns": payload.num_cols,
                }
            })
    return requests


def _element_text(element: dict) -> str:
    paragraph = element.get("paragraph") or {}
    return "".join(
        (el.get("textRun", {}) or {}).get("content", "")
        for el in paragraph.get("elements", []) or []
    )


def match_blocks(tab_raw: dict, blocks: list) -> list:
    """Match each model block to its element in the live document.

    Docs adds empty paragraphs, such as after a table. Skip unrelated elements
    instead of assuming fixed positions.
    """
    content = (tab_raw.get("body", {}) or {}).get("content", []) or []
    pairs: list = []
    cursor = 0
    for block in blocks:
        want_table = isinstance(block, Table)
        while cursor < len(content):
            element = content[cursor]
            cursor += 1
            if want_table and "table" in element:
                pairs.append((block, element))
                break
            if not want_table and "paragraph" in element:
                if _element_text(element).rstrip("\n") == block.text:
                    pairs.append((block, element))
                    break
        else:
            raise RuntimeError(
                f"Block {block!r} was not found in the document; "
                f"remote content does not match inserted content."
            )
    return pairs


def cell_text_requests(tab_raw: dict, blocks: list,
                       tab_id: Optional[str] = None) -> list:
    """Phase 2: fill cells from last to first.

    Each insert shifts later content. Reverse traversal keeps indexes from one
    read valid.
    """
    inserts: list = []
    for block, element in match_blocks(tab_raw, blocks):
        if not isinstance(block, Table):
            continue
        doc_rows = (element.get("table", {}) or {}).get("tableRows", []) or []
        for r_idx, row in enumerate(doc_rows):
            cells = row.get("tableCells", []) or []
            for c_idx, cell in enumerate(cells):
                if r_idx >= len(block.rows) or c_idx >= len(block.rows[r_idx]):
                    continue
                text = "\n".join(p.text for p in block.rows[r_idx][c_idx])
                if not text:
                    continue
                cell_content = cell.get("content", []) or []
                if not cell_content:
                    continue
                inserts.append((cell_content[0].get("startIndex", 0), text))

    inserts.sort(key=lambda pair: pair[0], reverse=True)
    return [
        {"insertText": {"location": _location(tab_id, index), "text": text}}
        for index, text in inserts
    ]


def _text_style(run: Run, code_font: str = CODE_FONT) -> tuple:
    style: dict = {"bold": run.bold, "italic": run.italic,
                   "strikethrough": run.strikethrough}
    fields = ["bold", "italic", "strikethrough"]
    if run.code:
        style["weightedFontFamily"] = {"fontFamily": code_font}
        fields.append("weightedFontFamily")
    if run.link:
        style["link"] = {"url": run.link}
        fields.append("link")
    return style, ",".join(fields)


def _paragraph_style(paragraph: Paragraph) -> tuple:
    style: dict = {"namedStyleType": paragraph.named_style}
    fields = ["namedStyleType"]
    indent = QUOTE_INDENT_PT if paragraph.quote else 0.0
    indent += NESTING_INDENT_PT * paragraph.nesting
    if indent:
        style["indentStart"] = {"magnitude": indent, "unit": "PT"}
        fields.append("indentStart")
    return style, ",".join(fields)


def style_requests(tab_raw: dict, blocks: list, tab_id: Optional[str] = None,
                   code_font: str = CODE_FONT) -> list:
    """Phase 3: apply paragraph, character, and bullet styles.

    These requests do not change text length, so one set of indexes remains
    valid for the batch. `createParagraphBullets` runs last because it alone
    can modify text by trimming existing markers.
    """
    requests: list = []
    bullets: list = []

    for block, element in match_blocks(tab_raw, blocks):
        if isinstance(block, Table):
            requests.extend(_table_cell_style_requests(block, element, tab_id, code_font))
            continue

        start = element.get("startIndex", 0)
        end = element.get("endIndex", start)
        style, fields = _paragraph_style(block)
        requests.append({
            "updateParagraphStyle": {
                "range": _range(tab_id, start, end),
                "paragraphStyle": style,
                "fields": fields,
            }
        })
        requests.extend(_run_style_requests(block.runs, start, tab_id, code_font))
        if block.bullet:
            bullets.append({
                "createParagraphBullets": {
                    "range": _range(tab_id, start, end),
                    "bulletPreset": BULLET_PRESET[block.bullet],
                }
            })

    return requests + bullets


def _run_style_requests(runs: list, start: int, tab_id: Optional[str],
                        code_font: str) -> list:
    requests: list = []
    offset = start
    for run in runs:
        length = u16len(run.text)
        if length:
            style, fields = _text_style(run, code_font)
            requests.append({
                "updateTextStyle": {
                    "range": _range(tab_id, offset, offset + length),
                    "textStyle": style,
                    "fields": fields,
                }
            })
        offset += length
    return requests


def _table_cell_style_requests(block: Table, element: dict, tab_id: Optional[str],
                               code_font: str) -> list:
    requests: list = []
    doc_rows = (element.get("table", {}) or {}).get("tableRows", []) or []
    for r_idx, row in enumerate(doc_rows):
        if r_idx >= len(block.rows):
            continue
        for c_idx, cell in enumerate(row.get("tableCells", []) or []):
            if c_idx >= len(block.rows[r_idx]):
                continue
            paragraphs = block.rows[r_idx][c_idx]
            cell_content = [el for el in (cell.get("content", []) or []) if "paragraph" in el]
            for p_idx, model_par in enumerate(paragraphs):
                if p_idx >= len(cell_content):
                    continue
                requests.extend(_run_style_requests(
                    model_par.runs, cell_content[p_idx].get("startIndex", 0),
                    tab_id, code_font,
                ))
    return requests
