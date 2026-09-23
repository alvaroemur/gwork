from __future__ import annotations

"""Extract reusable design tokens from Google Docs API responses."""

from collections import Counter
from typing import Any, Iterable, Optional

from .manifest import NAMED_STYLE_TO_SCALE
from .tokens import rgb_to_hex


def _paragraph_text(paragraph: dict) -> str:
    return "".join(
        element.get("textRun", {}).get("content", "")
        for element in paragraph.get("elements", [])
    ).strip()


def _color(value: Any) -> Optional[str]:
    if not isinstance(value, dict):
        return None
    rgb = value.get("rgbColor")
    if rgb is None:
        rgb = ((value.get("color", {}) or {}).get("rgbColor"))
    return rgb_to_hex(rgb) if rgb else None


def _run_token(run: dict) -> dict[str, Any]:
    style = (run.get("textRun", {}) or {}).get("textStyle", {}) or {}
    token: dict[str, Any] = {}
    font = (style.get("weightedFontFamily", {}) or {}).get("fontFamily")
    size = (style.get("fontSize", {}) or {}).get("magnitude")
    color = _color(style.get("foregroundColor"))
    background = _color(style.get("backgroundColor"))
    if font:
        token["font"] = font
    if size is not None:
        token["size"] = size
    if color:
        token["color"] = color
    if background:
        token["background"] = background
    if style.get("bold") is not None:
        token["weight"] = 700 if style["bold"] else 400
    if style.get("italic") is not None:
        token["italic"] = bool(style["italic"])
    return token


def _paragraph_token(paragraph: dict) -> dict[str, Any]:
    style = paragraph.get("paragraphStyle", {}) or {}
    token: dict[str, Any] = {}
    for run in paragraph.get("elements", []) or []:
        if (run.get("textRun", {}) or {}).get("content", "").strip():
            token.update(_run_token(run))
            break
    mapping = {
        "alignment": "alignment",
        "lineSpacing": "line_spacing",
        "spaceAbove": "space_above",
        "spaceBelow": "space_below",
    }
    for source, target in mapping.items():
        value = style.get(source)
        if isinstance(value, dict):
            value = value.get("magnitude")
        if value is not None:
            token[target] = value
    return token


def _iter_body_elements(raw: dict) -> Iterable[dict]:
    yield from (raw.get("body", {}) or {}).get("content", []) or []


def _dominant(values: list[Any]) -> Any:
    serializable = [str(value) for value in values if value not in (None, "")]
    return Counter(serializable).most_common(1)[0][0] if serializable else None


def extract_style_tokens(documents: Iterable[dict]) -> dict[str, Any]:
    """Infer typography and component tokens from one or more document tabs."""
    documents = list(documents)
    tokens: dict[str, Any] = {
        "typography": {},
        "colors": {},
        "components": {},
    }
    typography = tokens["typography"]
    colors = tokens["colors"]
    components = tokens["components"]
    body_fonts: list[str] = []
    code_fonts: list[str] = []

    for raw in documents:
        doc_style = raw.get("documentStyle", {}) or {}
        if "page_layout" not in tokens and doc_style:
            margins = {}
            for edge in ("top", "bottom", "left", "right"):
                value = (doc_style.get(f"margin{edge.capitalize()}", {}) or {}).get("magnitude")
                if value is not None:
                    margins[edge] = value
            page_layout: dict[str, Any] = {"margins": margins}
            width = (doc_style.get("pageSize", {}) or {}).get("width", {}).get("magnitude")
            if width is not None:
                page_layout["page_width"] = width
                page_layout["printable_width"] = width - margins.get("left", 0) - margins.get("right", 0)
            tokens["page_layout"] = page_layout

        for element in _iter_body_elements(raw):
            paragraph = element.get("paragraph")
            if paragraph:
                text = _paragraph_text(paragraph)
                if not text:
                    continue
                paragraph_style = paragraph.get("paragraphStyle", {}) or {}
                named_style = paragraph_style.get("namedStyleType", "NORMAL_TEXT")
                scale = NAMED_STYLE_TO_SCALE.get(named_style)
                token = _paragraph_token(paragraph)
                if scale and scale not in typography:
                    typography[scale] = token
                if named_style == "NORMAL_TEXT" and token.get("font"):
                    body_fonts.append(token["font"])

                shading = _color(
                    (paragraph_style.get("shading", {}) or {}).get("backgroundColor")
                )
                border = paragraph_style.get("borderLeft", {}) or {}
                border_color = _color(border.get("color"))
                indent = (paragraph_style.get("indentStart", {}) or {}).get("magnitude", 0)
                if (
                    shading
                    or border_color
                    or indent >= 24
                    or text.startswith((">", "💡", "⚠️", "📌"))
                ) and "callout" not in components:
                    callout: dict[str, Any] = {}
                    if shading:
                        callout["background"] = shading
                        colors["callout_bg"] = shading
                    if border_color:
                        width = (border.get("width", {}) or {}).get("magnitude", 1)
                        dash = border.get("dashStyle", "SOLID").lower()
                        callout["border_left"] = f"{width:g}pt {dash} {border_color}"
                        colors["callout_border"] = border_color
                    if indent:
                        callout["indent_start"] = indent
                    components["callout"] = callout

                if (
                    named_style == "NORMAL_TEXT"
                    and len(text) <= 48
                    and text.upper() == text
                    and any(char.isalpha() for char in text)
                    and "eyebrow" not in components
                ):
                    components["eyebrow"] = token

                for run in paragraph.get("elements", []) or []:
                    run_token = _run_token(run)
                    font = run_token.get("font", "")
                    if (
                        run_token.get("background")
                        or "mono" in font.lower()
                        or font in {"Courier New", "Roboto Mono", "Consolas"}
                    ):
                        if font:
                            code_fonts.append(font)
                        components.setdefault("inline_code", run_token)
                        if run_token.get("background"):
                            colors.setdefault("technical_code_bg", run_token["background"])
                        if run_token.get("color"):
                            colors.setdefault("technical_code_text", run_token["color"])

            table = element.get("table")
            if table and "tables" not in components:
                table_token: dict[str, Any] = {}
                rows = table.get("tableRows", []) or []
                cells = rows[0].get("tableCells", []) if rows else []
                if cells:
                    cell_style = cells[0].get("tableCellStyle", {}) or {}
                    background = _color(cell_style.get("backgroundColor"))
                    if background:
                        table_token["header_background"] = background
                        colors["table_header_bg"] = background
                    for child in cells[0].get("content", []) or []:
                        if child.get("paragraph"):
                            header_token = _paragraph_token(child["paragraph"])
                            if header_token.get("color"):
                                table_token["header_text"] = header_token["color"]
                                colors["table_header_text"] = header_token["color"]
                            break
                    padding = {}
                    for edge in ("top", "bottom", "left", "right"):
                        value = (cell_style.get(f"padding{edge.capitalize()}", {}) or {}).get(
                            "magnitude"
                        )
                        if value is not None:
                            padding[edge] = value
                    if padding:
                        table_token["padding"] = padding
                components["tables"] = table_token

    primary_font = _dominant(body_fonts)
    code_font = _dominant(code_fonts)
    if primary_font:
        typography["font_family_primary"] = primary_font
    if code_font:
        typography["font_family_code"] = code_font
    return tokens


def template_markdown(tokens: dict[str, Any]) -> str:
    """Build a compact visual specimen for the extracted token set."""
    sections = [
        "# Design token template",
        "",
        "EYEBROW",
        "",
        "## Heading 1",
        "",
        "### Heading 2",
        "",
        "#### Heading 3",
        "",
        "Normal body text for typography and spacing.",
        "",
        "> 💡 Callout sample",
        "",
        "Inline `code sample` inside body text.",
        "",
        "| Header A | Header B |",
        "| --- | --- |",
        "| Value A | Value B |",
        "",
    ]
    return "\n".join(sections)
