from __future__ import annotations

"""Translate a ``StyleSyncEngine`` plan into ``documents.batchUpdate`` requests.

These requests do not change text length, so plan indices remain valid for the
entire batch. Structural mutations, such as deleting dividers, run first in a
separate phase.
"""

from .tokens import hex_to_rgb

CELL_PADDING_FIELDS = "backgroundColor,paddingTop,paddingBottom,paddingLeft,paddingRight"


def _range(tab_id, start: int, end: int) -> dict:
    rng = {"startIndex": start, "endIndex": end}
    if tab_id:
        rng["tabId"] = tab_id
    return rng


def _table_start(tab_id, index: int) -> dict:
    loc = {"index": index}
    if tab_id:
        loc["tabId"] = tab_id
    return loc


def _cell_style(bg: str, padding: dict) -> dict:
    return {
        "backgroundColor": {"color": {"rgbColor": hex_to_rgb(bg)}},
        "paddingTop": {"magnitude": padding["top"], "unit": "PT"},
        "paddingBottom": {"magnitude": padding["bottom"], "unit": "PT"},
        "paddingLeft": {"magnitude": padding["left"], "unit": "PT"},
        "paddingRight": {"magnitude": padding["right"], "unit": "PT"},
    }


def _row_style_request(tab_id, t_start: int, row: int, cols: int,
                       bg: str, padding: dict) -> dict:
    return {
        "updateTableCellStyle": {
            "tableRange": {
                "tableCellLocation": {
                    "tableStartLocation": _table_start(tab_id, t_start),
                    "rowIndex": row,
                    "columnIndex": 0,
                },
                "rowSpan": 1,
                "columnSpan": cols,
            },
            "tableCellStyle": _cell_style(bg, padding),
            "fields": CELL_PADDING_FIELDS,
        }
    }


def build_requests(plan: dict, tab_id=None, restore_table_widths: bool = True,
                   cell_padding: dict = None, header_padding: dict = None) -> list:
    """Compile the atomic style batch for one tab."""
    cell_padding = cell_padding or {"top": 3.5, "bottom": 3.5, "left": 4.5, "right": 4.5}
    header_padding = header_padding or {"top": 4.0, "bottom": 4.0, "left": 5.0, "right": 5.0}
    requests: list = []

    for pu in plan.get("paragraph_updates", []):
        requests.append({
            "updateParagraphStyle": {
                "range": _range(tab_id, pu["start"], pu["end"]),
                "paragraphStyle": pu["paragraphStyle"],
                "fields": pu["fields"],
            }
        })

    for cu in plan.get("callout_updates", []):
        requests.append({
            "updateParagraphStyle": {
                "range": _range(tab_id, cu["start"], cu["end"]),
                "paragraphStyle": {
                    "shading": {"backgroundColor": {"color": {"rgbColor": hex_to_rgb(cu["bg"])}}},
                    "borderLeft": {
                        "color": {"color": {"rgbColor": hex_to_rgb(cu["border_color"])}},
                        "dashStyle": cu["border_style"],
                        "padding": {"magnitude": cu["padding_left"], "unit": "PT"},
                        "width": {"magnitude": cu["border_width"], "unit": "PT"},
                    },
                    "spaceAbove": {"magnitude": cu["space_above"], "unit": "PT"},
                    "spaceBelow": {"magnitude": cu["space_below"], "unit": "PT"},
                    "indentStart": {"magnitude": cu["indent_start"], "unit": "PT"},
                },
                "fields": "shading,borderLeft,spaceAbove,spaceBelow,indentStart",
            }
        })

    for tu in plan.get("text_updates", []):
        text_style = {"weightedFontFamily": {"fontFamily": tu["font_family"]}}
        fields = ["weightedFontFamily"]
        if tu.get("size"):
            text_style["fontSize"] = {"magnitude": tu["size"], "unit": "PT"}
            fields.append("fontSize")
        if tu.get("is_heading"):
            if tu.get("color"):
                text_style["foregroundColor"] = {"color": {"rgbColor": hex_to_rgb(tu["color"])}}
                fields.append("foregroundColor")
            if tu.get("bg_color"):
                text_style["backgroundColor"] = {"color": {"rgbColor": hex_to_rgb(tu["bg_color"])}}
                fields.append("backgroundColor")
            if tu.get("bold") is not None:
                text_style["bold"] = tu["bold"]
                fields.append("bold")
        requests.append({
            "updateTextStyle": {
                "range": _range(tab_id, tu["start"], tu["end"]),
                "textStyle": text_style,
                "fields": ",".join(fields),
            }
        })

    for tbl in plan.get("table_updates", []):
        t_start = tbl["start_index"]
        cols = tbl["columns"]

        requests.append(_row_style_request(
            tab_id, t_start, 0, cols, tbl["header"]["bg"], header_padding
        ))
        for zr in tbl["zebra_rows"]:
            requests.append(_row_style_request(
                tab_id, t_start, zr["row"], cols, zr["bg"], cell_padding
            ))
        if tbl["summary_row"]:
            sr = tbl["summary_row"]
            requests.append(_row_style_request(
                tab_id, t_start, sr["row"], cols, sr["bg"], cell_padding
            ))

        for ctu in tbl["cell_text_updates"]:
            requests.append({
                "updateTextStyle": {
                    "range": _range(tab_id, ctu["start"], ctu["end"]),
                    "textStyle": {
                        "weightedFontFamily": {"fontFamily": ctu["font_family"]},
                        "fontSize": {"magnitude": ctu["size"], "unit": "PT"},
                        "foregroundColor": {"color": {"rgbColor": hex_to_rgb(ctu["color"])}},
                        "bold": ctu["bold"],
                    },
                    "fields": "weightedFontFamily,fontSize,foregroundColor,bold",
                }
            })

        if restore_table_widths:
            for col_i, col_w in enumerate(tbl["target_widths"]):
                requests.append({
                    "updateTableColumnProperties": {
                        "tableStartLocation": _table_start(tab_id, t_start),
                        "columnIndices": [col_i],
                        "tableColumnProperties": {
                            "widthType": "FIXED_WIDTH",
                            "width": {"magnitude": col_w, "unit": "PT"},
                        },
                        "fields": "width,widthType",
                    }
                })

    return requests
