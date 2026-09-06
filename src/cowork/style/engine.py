from __future__ import annotations

"""Análisis de una pestaña viva contra el manifiesto de diseño.

`analyze` es puro: recibe el JSON crudo de `Documents.Get` (o de una pestaña) y
devuelve un plan declarativo. El transporte y la escritura viven fuera.
"""

import re
from typing import Any, Optional

from .manifest import StyleManifest
from .tokens import (
    colors_match,
    hex_to_rgb,
    is_bold_weight,
    parse_border,
    parse_pt,
    rgb_to_hex,
)

BADGE_RE = re.compile(r"\[(ESTADO|STATUS|FASE|PRIORIDAD|ROL):?\s*[^\]]+\]", re.IGNORECASE)
DIVIDER_RE = re.compile(r"^[-–—\s]{3,}$")
CALLOUT_HINT_RE = re.compile(
    r"\b(callout|alerta|advertencia|nota|importante|recomendaci[óo]n)\b", re.IGNORECASE
)
CALLOUT_ICONS = ("💡", "⚠️", "📌")
HEADING_ELEMENTS = ("title", "subtitle", "heading_1", "heading_2", "heading_3", "heading_4")


def _paragraph_text(paragraph: dict) -> str:
    return "".join(
        el.get("textRun", {}).get("content", "") for el in paragraph.get("elements", [])
    )


def empty_plan(tab_id: str, tab_title: str) -> dict:
    return {
        "tab_id": tab_id,
        "tab_title": tab_title,
        "dividers_to_remove": [],
        "page_layout": {},
        "paragraph_updates": [],
        "callout_updates": [],
        "text_updates": [],
        "table_updates": [],
        "links_preserved": [],
        "audit_issues": [],
    }


class StyleSyncEngine:
    """Cataloga desviaciones entre una pestaña y el sistema de diseño."""

    def __init__(self, manifest: StyleManifest):
        self.manifest = manifest

    # -- entrada principal -------------------------------------------------

    def analyze(self, tab_raw: dict, tab_id: str, tab_title: str) -> dict:
        plan = empty_plan(tab_id, tab_title)
        content = (tab_raw.get("body", {}) or {}).get("content", []) or []

        self._audit_page_layout(tab_raw, plan)

        title_idx, subtitle_idx = self._locate_title_and_subtitle(content)

        table_counter = 0
        for idx, el in enumerate(content):
            if "paragraph" in el:
                self._analyze_paragraph(el, idx, plan, title_idx, subtitle_idx)
            elif "table" in el:
                table_counter += 1
                self._analyze_table(el, table_counter, plan)
        return plan

    # -- page layout -------------------------------------------------------

    def _audit_page_layout(self, tab_raw: dict, plan: dict) -> None:
        doc_style = tab_raw.get("documentStyle", {}) or {}
        margins_cfg = self.manifest.page_layout.get("margins", {}) or {}
        for edge in ("top", "bottom", "left", "right"):
            expected = parse_pt(margins_cfg.get(edge, "35pt"))
            actual = (doc_style.get(f"margin{edge.capitalize()}", {}) or {}).get("magnitude", 0.0)
            if abs(actual - expected) > 1.0:
                plan["audit_issues"].append(
                    f"Margen {edge}: esperado {expected}pt, actual {actual}pt"
                )
        plan["page_layout"] = {
            "size": self.manifest.page_layout.get("size", "Letter"),
            "margins": margins_cfg,
            "printable_width": self.manifest.printable_width,
        }

    # -- jerarquía ---------------------------------------------------------

    def _locate_title_and_subtitle(self, content: list) -> tuple:
        title_idx: Optional[int] = None
        subtitle_idx: Optional[int] = None
        for idx, el in enumerate(content):
            if "paragraph" not in el:
                continue
            p = el["paragraph"]
            named = (p.get("paragraphStyle", {}) or {}).get("namedStyleType", "NORMAL_TEXT")
            text = _paragraph_text(p).strip()
            if not text:
                continue
            if named == "TITLE":
                title_idx = idx
                break
            if named == "SUBTITLE" and subtitle_idx is None:
                subtitle_idx = idx
            elif idx < 2 and text.isupper() and len(text) < 45 and subtitle_idx is None:
                subtitle_idx = idx
            elif title_idx is None and named == "HEADING_1" and not re.match(r"^\d+\.", text) and idx < 3:
                title_idx = idx
        return title_idx, subtitle_idx

    def _resolve_scale(self, named_style: str, text: str, idx: int,
                       title_idx: Optional[int], subtitle_idx: Optional[int]) -> tuple:
        """Devuelve (scale_key, namedStyleType objetivo) para un párrafo."""
        if idx == subtitle_idx or named_style == "SUBTITLE":
            return "subtitle", "SUBTITLE"
        if idx == title_idx or named_style == "TITLE":
            return "title", "TITLE"
        if named_style == "HEADING_1":
            return "heading_1", "HEADING_1"
        if named_style == "HEADING_2":
            if re.match(r"^\d+\.\s+[^\d]", text):
                return "heading_1", "HEADING_1"
            return "heading_2", "HEADING_2"
        if named_style == "HEADING_3":
            if re.match(r"^\d+\.\d+\s+[^\d]", text):
                return "heading_2", "HEADING_2"
            return "heading_3", "HEADING_3"
        if named_style == "HEADING_4":
            if re.match(r"^\d+\.\d+\.\d+\s+", text):
                return "heading_3", "HEADING_3"
            return "heading_4", "HEADING_4"
        if named_style in ("HEADING_5", "HEADING_6"):
            return "heading_4", "HEADING_4"
        if named_style == "NORMAL_TEXT":
            if re.match(r"^\d+\.\d+\.\d+\.\d+\s+", text):
                return "heading_4", "HEADING_4"
            if re.match(r"^\d+\.\d+\.\d+\s+", text):
                return "heading_3", "HEADING_3"
            if re.match(r"^\d+\.\d+\s+", text):
                return "heading_2", "HEADING_2"
            if re.match(r"^\d+\.\s+[^\d]", text):
                return "heading_1", "HEADING_1"
            return "normal_text", "NORMAL_TEXT"
        return None, named_style

    # -- párrafos ----------------------------------------------------------

    def _analyze_paragraph(self, el: dict, idx: int, plan: dict,
                           title_idx: Optional[int], subtitle_idx: Optional[int]) -> None:
        p = el["paragraph"]
        p_style = p.get("paragraphStyle", {}) or {}
        named_style = p_style.get("namedStyleType", "NORMAL_TEXT")
        runs = p.get("elements", []) or []
        p_text = _paragraph_text(p)
        text = p_text.strip()
        p_start = el.get("startIndex", 0)
        p_end = el.get("endIndex", 0)
        if not text:
            return

        if DIVIDER_RE.match(text):
            plan["dividers_to_remove"].append({"start": p_start, "end": p_end, "text": text})
            plan["audit_issues"].append(
                f"Separador residual detectado en [{p_start}:{p_end}]: {text!r}"
            )
            return

        for r in runs:
            link = ((r.get("textRun", {}) or {}).get("textStyle", {}) or {}).get("link")
            if link and link.get("url"):
                plan["links_preserved"].append({
                    "text": r["textRun"].get("content", "").strip(),
                    "url": link["url"],
                    "range": [r.get("startIndex"), r.get("endIndex")],
                })

        if self._is_callout(text, p_style):
            self._plan_callout(text, p_style, p_start, p_end, plan)
            return

        scale_key, target_named = self._resolve_scale(named_style, text, idx, title_idx, subtitle_idx)
        if scale_key and scale_key in self.manifest.scales:
            self._plan_scale(scale_key, target_named, named_style, text, p_style,
                             runs, p_start, p_end, plan)

        self._plan_character_tokens(p_text, runs, p_start, plan)

    def _is_callout(self, text: str, p_style: dict) -> bool:
        indent = (p_style.get("indentStart", {}) or {}).get("magnitude", 0.0)
        return bool(
            text.startswith(">")
            or "borderLeft" in p_style
            or "shading" in p_style
            or indent >= 30.0
            or any(text.startswith(icon) for icon in CALLOUT_ICONS)
            or (len(text) < 70 and CALLOUT_HINT_RE.search(text))
        )

    def _plan_callout(self, text: str, p_style: dict, p_start: int, p_end: int,
                      plan: dict) -> None:
        cfg = self.manifest.components.get("callouts", {}) or {}
        bg = cfg.get("background", self.manifest.color("callout_bg", "#F8F6FA"))
        border_w, border_style, border_col = parse_border(
            cfg.get("border_left", f"3pt solid {self.manifest.color('callout_border', '#E6007E')}")
        )

        cur_border = p_style.get("borderLeft")
        cur_shading = (
            ((p_style.get("shading", {}) or {}).get("backgroundColor", {}) or {})
            .get("color", {}) or {}
        ).get("rgbColor")
        if not cur_border or not colors_match(
            border_col, ((cur_border.get("color", {}) or {}).get("color", {}) or {}).get("rgbColor")
        ):
            plan["audit_issues"].append(
                f"Callout en [{p_start}:{p_end}] carece de borde lateral {border_col}"
            )
        if not cur_shading or not colors_match(bg, cur_shading):
            plan["audit_issues"].append(f"Callout en [{p_start}:{p_end}] carece de fondo {bg}")

        plan["callout_updates"].append({
            "start": p_start,
            "end": p_end,
            "bg": bg,
            "border_color": border_col,
            "border_width": border_w,
            "border_style": border_style,
            "padding_left": parse_pt(cfg.get("padding_left", "6pt")),
            "space_above": parse_pt(cfg.get("space_above", "10pt")),
            "space_below": parse_pt(cfg.get("space_below", "10pt")),
            "indent_start": 12.0,
            "text_sample": text[:40],
        })

    def _plan_scale(self, scale_key: str, target_named: str, named_style: str, text: str,
                    p_style: dict, runs: list, p_start: int, p_end: int, plan: dict) -> None:
        rule = self.manifest.scales[scale_key]
        style_req: dict = {}
        fields: list = []

        if named_style != target_named:
            style_req["namedStyleType"] = target_named
            fields.append("namedStyleType")
            plan["audit_issues"].append(
                f"{text[:30]}: estilo actual {named_style} != objetivo {target_named}"
            )

        expected_align = rule.get("alignment")
        if expected_align:
            current = p_style.get("alignment", "START")
            if current != expected_align:
                style_req["alignment"] = expected_align
                fields.append("alignment")
                plan["audit_issues"].append(
                    f"{scale_key} en [{p_start}:{p_end}]: alineación {current} != {expected_align}"
                )

        for key, api_field in (("space_above", "spaceAbove"), ("space_below", "spaceBelow")):
            if key not in rule:
                continue
            expected = parse_pt(rule[key])
            current = (p_style.get(api_field, {}) or {}).get("magnitude", 0.0)
            if abs(current - expected) > 0.5:
                style_req[api_field] = {"magnitude": expected, "unit": "PT"}
                fields.append(api_field)
                if abs(current - expected) > 1.0:
                    plan["audit_issues"].append(
                        f"{scale_key} en [{p_start}:{p_end}]: {api_field} {current}pt != {expected}pt"
                    )

        if "line_spacing" in rule:
            expected_ls = float(rule["line_spacing"])
            current_ls = p_style.get("lineSpacing", 100.0)
            if abs(current_ls - expected_ls) > 5.0:
                style_req["lineSpacing"] = expected_ls
                fields.append("lineSpacing")

        if "border_bottom" in rule:
            bb_width, bb_style, bb_color = parse_border(rule["border_bottom"])
            current_bb = p_style.get("borderBottom")
            matches = (
                current_bb is not None
                and colors_match(
                    bb_color,
                    ((current_bb.get("color", {}) or {}).get("color", {}) or {}).get("rgbColor"),
                )
                and abs((current_bb.get("width", {}) or {}).get("magnitude", 0.0) - bb_width) <= 0.2
            )
            if not matches:
                plan["audit_issues"].append(
                    f"Heading 3 en [{p_start}:{p_end}] carece de borde inferior {bb_color}"
                )
            style_req["borderBottom"] = {
                "color": {"color": {"rgbColor": hex_to_rgb(bb_color)}},
                "dashStyle": bb_style,
                "padding": {"magnitude": 4, "unit": "PT"},
                "width": {"magnitude": bb_width, "unit": "PT"},
            }
            fields.append("borderBottom")

        if fields:
            plan["paragraph_updates"].append({
                "start": p_start,
                "end": p_end,
                "fields": ",".join(fields),
                "paragraphStyle": style_req,
                "style_name": scale_key,
                "text_sample": text[:40],
            })

        expected_size = rule.get("size")
        expected_color = rule.get("color")
        is_heading = scale_key in HEADING_ELEMENTS
        expected_bold = is_bold_weight(rule.get("weight", 400)) if is_heading else None

        self._audit_runs(runs, scale_key, expected_size, expected_color, is_heading, plan)

        plan["text_updates"].append({
            "start": p_start,
            "end": p_end,
            "font_family": self.manifest.font_primary,
            "size": expected_size,
            "color": expected_color,
            "bold": expected_bold,
            "is_heading": is_heading,
            "style_name": scale_key,
        })

    def _audit_runs(self, runs: list, scale_key: str, expected_size: Any,
                    expected_color: Any, is_heading: bool, plan: dict) -> None:
        font_primary = self.manifest.font_primary
        font_code = self.manifest.font_code
        for r in runs:
            tr = r.get("textRun", {}) or {}
            text = tr.get("content", "").strip()
            if not text:
                continue
            style = tr.get("textStyle", {}) or {}
            if style.get("link"):
                continue
            # Badges y código técnico van a 9pt por diseño; no son desviaciones.
            if BADGE_RE.search(text) or style.get("backgroundColor"):
                continue

            font = (style.get("weightedFontFamily", {}) or {}).get("fontFamily")
            size = (style.get("fontSize", {}) or {}).get("magnitude")
            color = ((style.get("foregroundColor", {}) or {}).get("color", {}) or {}).get("rgbColor")

            if font and font not in (font_primary, font_code):
                plan["audit_issues"].append(
                    f"{scale_key} [{r.get('startIndex')}:{r.get('endIndex')}]: "
                    f"fuente '{font}' != '{font_primary}'"
                )
            if size and expected_size and abs(size - expected_size) > 0.5:
                plan["audit_issues"].append(
                    f"{scale_key} [{r.get('startIndex')}:{r.get('endIndex')}]: "
                    f"tamaño {size}pt != {expected_size}pt"
                )
            if is_heading and expected_color and color and not colors_match(expected_color, color):
                plan["audit_issues"].append(
                    f"{scale_key} [{r.get('startIndex')}:{r.get('endIndex')}]: "
                    f"color {rgb_to_hex(color)} != {expected_color}"
                )

    # -- tokens de carácter ------------------------------------------------

    def _plan_character_tokens(self, p_text: str, runs: list, p_start: int, plan: dict) -> None:
        font_primary = self.manifest.font_primary
        font_code = self.manifest.font_code

        for match in BADGE_RE.finditer(p_text):
            plan["text_updates"].append({
                "start": p_start + match.start(),
                "end": p_start + match.end(),
                "font_family": font_primary,
                "size": 9,
                "color": self.manifest.color("badge_text", "#6A3FA0"),
                "bg_color": self.manifest.color("badge_bg", "#F3E8FF"),
                "bold": True,
                "is_heading": True,
                "style_name": "badge",
            })

        for r in runs:
            tr = r.get("textRun", {}) or {}
            content = tr.get("content", "")
            found_backticks = False
            for match in re.finditer(r"`([^`]+)`", content):
                found_backticks = True
                plan["text_updates"].append(self._code_update(
                    r["startIndex"] + match.start(), r["startIndex"] + match.end(), font_code
                ))
            # La importación Markdown de Docs come los backticks y deja Courier New:
            # hay que reconocer también ese caso o se pierden los fragmentos técnicos.
            already_code = (
                (tr.get("textStyle", {}) or {}).get("weightedFontFamily", {}) or {}
            ).get("fontFamily") == font_code
            if not found_backticks and already_code and content.strip():
                plan["text_updates"].append(
                    self._code_update(r["startIndex"], r["endIndex"], font_code)
                )

        terms = (self.manifest.components.get("key_concepts", {}) or {}).get("terms", [])
        if terms:
            pattern = r"\b(" + "|".join(re.escape(t) for t in terms) + r")\b"
            for match in re.finditer(pattern, p_text, re.IGNORECASE):
                plan["text_updates"].append({
                    "start": p_start + match.start(),
                    "end": p_start + match.end(),
                    "font_family": font_primary,
                    "size": 10,
                    "color": self.manifest.color("secondary", "#6A3FA0"),
                    "bold": True,
                    "is_heading": True,
                    "style_name": "key_concept",
                })

    def _code_update(self, start: int, end: int, font_code: str) -> dict:
        return {
            "start": start,
            "end": end,
            "font_family": font_code,
            "size": 9,
            "color": self.manifest.color("technical_code_text", "#202124"),
            "bg_color": self.manifest.color("technical_code_bg", "#F1F3F4"),
            "bold": False,
            "is_heading": True,
            "style_name": "technical_word",
        }

    # -- tablas ------------------------------------------------------------

    def _analyze_table(self, el: dict, table_index: int, plan: dict) -> None:
        table = el["table"]
        t_start = el.get("startIndex", 0)
        num_rows = table.get("rows", 0)
        num_cols = table.get("columns", 0)

        cfg = self.manifest.components.get("tables", {}) or {}
        header_bg = self.manifest.color("table_header_bg", "#E6007E")
        header_text = self.manifest.color("table_header_text", "#FFFFFF")
        even_bg = self.manifest.color("table_zebra_even", "#FFFFFF")
        odd_bg = self.manifest.color("table_zebra_odd", "#F5F5F5")
        summary_bg = self.manifest.color("table_summary_bg", "#FFBBE0")
        printable_w = self.manifest.printable_width

        col_props = (table.get("tableStyle", {}) or {}).get("tableColumnProperties", []) or []
        existing = [(cp.get("width", {}) or {}).get("magnitude", 0.0) for cp in col_props]
        target_widths = distribute_widths(existing, num_cols, printable_w)

        table_plan = {
            "table_index": table_index,
            "start_index": t_start,
            "rows": num_rows,
            "columns": num_cols,
            "target_widths": target_widths,
            "pin_header": cfg.get("pin_header", True),
            "header": {"row": 0, "bg": header_bg, "text_color": header_text},
            "zebra_rows": [],
            "summary_row": None,
            "cell_text_updates": [],
        }

        if not widths_conform(col_props, num_cols, sum(existing), printable_w):
            plan["audit_issues"].append(
                f"Tabla #{table_index} [{t_start}]: anchos no fijados a {printable_w}pt "
                f"(actual {sum(existing):.1f}pt)"
            )

        font_primary = self.manifest.font_primary
        for r_idx, row in enumerate(table.get("tableRows", []) or []):
            cells = row.get("tableCells", []) or []
            first_text = ""
            if cells:
                for c_el in cells[0].get("content", []) or []:
                    if "paragraph" in c_el:
                        first_text += _paragraph_text(c_el["paragraph"])
            lowered = first_text.lower()
            is_summary = (
                "total" in lowered or "resumen" in lowered or "suma" in lowered
                or (r_idx == num_rows - 1 and num_rows > 3)
            )
            cell_bg = self._first_cell_bg(cells)

            if r_idx == 0:
                if not colors_match(header_bg, cell_bg):
                    plan["audit_issues"].append(
                        f"Tabla #{table_index}: cabecera carece de color {header_bg}"
                    )
                self._collect_cell_runs(cells, table_plan, font_primary, header_text, True)
            elif is_summary:
                table_plan["summary_row"] = {"row": r_idx, "bg": summary_bg}
                if not colors_match(summary_bg, cell_bg):
                    plan["audit_issues"].append(
                        f"Tabla #{table_index}: fila de resumen carece de color {summary_bg}"
                    )
                self._collect_cell_runs(cells, table_plan, font_primary, "#000000", True)
            else:
                bg = even_bg if (r_idx % 2 == 1) else odd_bg
                table_plan["zebra_rows"].append({"row": r_idx, "bg": bg})
                if not colors_match(bg, cell_bg):
                    plan["audit_issues"].append(
                        f"Tabla #{table_index} (fila {r_idx}): fondo no coincide con cebreado ({bg})"
                    )

        plan["table_updates"].append(table_plan)

    @staticmethod
    def _first_cell_bg(cells: list) -> Optional[dict]:
        if not cells:
            return None
        style = cells[0].get("tableCellStyle", {}) or {}
        return ((style.get("backgroundColor", {}) or {}).get("color", {}) or {}).get("rgbColor")

    @staticmethod
    def _collect_cell_runs(cells: list, table_plan: dict, font: str,
                           color: str, bold: bool) -> None:
        for cell in cells:
            for c_el in cell.get("content", []) or []:
                if "paragraph" not in c_el:
                    continue
                for run in c_el["paragraph"].get("elements", []) or []:
                    if "startIndex" not in run or "endIndex" not in run:
                        continue
                    table_plan["cell_text_updates"].append({
                        "start": run["startIndex"],
                        "end": run["endIndex"],
                        "font_family": font,
                        "size": 10,
                        "color": color,
                        "bold": bold,
                    })


def distribute_widths(existing: list, num_cols: int, printable_w: float) -> list:
    """Anchos objetivo que suman exactamente `printable_w`.

    Si ya hay anchos asimétricos, se escalan proporcionalmente; si no, se
    reparten en partes iguales. El redondeo se absorbe en la última columna.
    """
    if num_cols <= 0:
        return []
    total = sum(existing)
    asymmetric = (
        total > 10
        and len(existing) == num_cols
        and any(abs(w - existing[0]) > 2 for w in existing)
    )
    if asymmetric:
        widths = [round(w * printable_w / total, 1) for w in existing]
    else:
        widths = [round(printable_w / num_cols, 1)] * num_cols
    widths[-1] = round(printable_w - sum(widths[:-1]), 1)
    return widths


def widths_conform(col_props: list, num_cols: int, sum_existing: float,
                   printable_w: float) -> bool:
    """True si las columnas ya están fijadas y suman el ancho útil."""
    if not col_props or len(col_props) != num_cols:
        return False
    if any(cp.get("widthType") != "FIXED_WIDTH" for cp in col_props):
        return False
    return abs(sum_existing - printable_w) <= 1.5
