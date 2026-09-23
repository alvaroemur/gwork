"""Tests for style engine tokens, hierarchy, tables, and requests."""

import pytest

from gwork.style.engine import (
    StyleSyncEngine,
    distribute_widths,
    widths_conform,
)
from gwork.style.manifest import StyleManifest
from gwork.style.requests_builder import build_requests
from gwork.style.tokens import (
    colors_match,
    hex_to_rgb,
    is_bold_weight,
    parse_border,
    parse_pt,
    rgb_to_hex,
)


MANIFEST_DATA = {
    "transport": {"provider": "gog", "account": "user@example.com"},
    "style": {
        "document_id": "DOC",
        "tokens": {
            "page_layout": {
                "size": "Letter",
                "margins": {"top": "35pt", "bottom": "35pt", "left": "35pt", "right": "35pt"},
                "printable_width": 542,
            },
            "typography": {
                "font_family_primary": "Nunito",
                "font_family_code": "Courier New",
                "heading_1": {"size": 18, "weight": 900, "color": "#E6007E",
                              "space_above": 18, "space_below": 7},
                "heading_2": {"size": 14, "weight": 900, "color": "#000000"},
                "heading_3": {"size": 12, "weight": 900, "color": "#6A3FA0",
                              "border_bottom": "1.25pt solid #E6007E"},
                "normal_text": {"size": 10, "weight": 400, "alignment": "JUSTIFIED",
                                "space_below": 6},
            },
            "colors": {"table_header_bg": "#E6007E", "secondary": "#6A3FA0"},
            "components": {"key_concepts": {"terms": ["bioeconomy"]}},
        },
        "sync_guards": {"remove_dash_dividers": True},
    },
}


@pytest.fixture
def manifest():
    return StyleManifest(MANIFEST_DATA)


def _paragraph(text, named_style="NORMAL_TEXT", start=1, style=None):
    end = start + len(text)
    return {
        "startIndex": start,
        "endIndex": end,
        "paragraph": {
            "paragraphStyle": dict({"namedStyleType": named_style}, **(style or {})),
            "elements": [{"startIndex": start, "endIndex": end,
                          "textRun": {"content": text, "textStyle": {}}}],
        },
    }


def _doc(*elements, margins=35.0):
    return {
        "documentStyle": {
            "marginTop": {"magnitude": margins},
            "marginBottom": {"magnitude": margins},
            "marginLeft": {"magnitude": margins},
            "marginRight": {"magnitude": margins},
        },
        "body": {"content": list(elements)},
    }


# --- tokens ---------------------------------------------------------------

def test_hex_to_rgb_accepts_short_form():
    assert hex_to_rgb("#FFF") == {"red": 1.0, "green": 1.0, "blue": 1.0}
    assert hex_to_rgb("#000000") == {"red": 0.0, "green": 0.0, "blue": 0.0}


def test_hex_rgb_round_trip():
    assert rgb_to_hex(hex_to_rgb("#E6007E")) == "#E6007E"


def test_parse_pt_accepts_number_and_string():
    assert parse_pt(12) == 12.0
    assert parse_pt("3.5pt") == 3.5
    assert parse_pt(None) == 0.0
    assert parse_pt("wide") == 0.0


def test_parse_border_complete():
    assert parse_border("1.25pt solid #E6007E") == (1.25, "SOLID", "#E6007E")
    assert parse_border("2pt dashed #000")[1] == "DASH"
    assert parse_border(None) == (1.0, "SOLID", "#000000")


def test_colors_match_with_tolerance():
    assert colors_match("#E6007E", hex_to_rgb("#E6007E"))
    assert not colors_match("#E6007E", hex_to_rgb("#000000"))
    assert not colors_match("#E6007E", None)


def test_is_bold_weight():
    assert is_bold_weight(900)
    assert is_bold_weight(700)
    assert not is_bold_weight(400)
    assert not is_bold_weight(None)


# --- hierarchy ------------------------------------------------------------

def test_numbered_heading_is_promoted(manifest):
    plan = StyleSyncEngine(manifest).analyze(
        _doc(_paragraph("2. Methodology\n", "HEADING_2")), "t.0", "Tab"
    )
    update = plan["paragraph_updates"][0]
    assert update["paragraphStyle"]["namedStyleType"] == "HEADING_1"
    assert update["style_name"] == "heading_1"


def test_numbered_normal_text_is_recognized_as_heading(manifest):
    plan = StyleSyncEngine(manifest).analyze(
        _doc(_paragraph("3.1 Scope\n", "NORMAL_TEXT")), "t.0", "Tab"
    )
    assert plan["paragraph_updates"][0]["paragraphStyle"]["namedStyleType"] == "HEADING_2"


def test_heading_3_receives_bottom_border(manifest):
    plan = StyleSyncEngine(manifest).analyze(
        _doc(_paragraph("Criteria\n", "HEADING_3")), "t.0", "Tab"
    )
    border = plan["paragraph_updates"][0]["paragraphStyle"]["borderBottom"]
    assert border["width"] == {"magnitude": 1.25, "unit": "PT"}
    assert border["color"]["color"]["rgbColor"] == hex_to_rgb("#E6007E")


def test_dash_divider_is_marked_for_removal(manifest):
    plan = StyleSyncEngine(manifest).analyze(
        _doc(_paragraph("--------------------\n")), "t.0", "Tab"
    )
    assert len(plan["dividers_to_remove"]) == 1
    assert plan["paragraph_updates"] == []


def test_margin_outside_tolerance_is_reported(manifest):
    plan = StyleSyncEngine(manifest).analyze(_doc(margins=72.0), "t.0", "Tab")
    assert sum(1 for i in plan["audit_issues"] if i.startswith("Margin")) == 4


def test_user_link_is_preserved(manifest):
    element = _paragraph("see the record\n")
    element["paragraph"]["elements"][0]["textRun"]["textStyle"] = {
        "link": {"url": "https://example.com"}
    }
    plan = StyleSyncEngine(manifest).analyze(_doc(element), "t.0", "Tab")
    assert plan["links_preserved"][0]["url"] == "https://example.com"


def test_callout_detected_by_indent(manifest):
    element = _paragraph("Indented callout text\n",
                         style={"indentStart": {"magnitude": 36.0}})
    plan = StyleSyncEngine(manifest).analyze(_doc(element), "t.0", "Tab")
    assert len(plan["callout_updates"]) == 1
    assert plan["callout_updates"][0]["indent_start"] == 12.0


def test_badge_and_key_concept_generate_ranges(manifest):
    plan = StyleSyncEngine(manifest).analyze(
        _doc(_paragraph("Bioeconomy advances [STATUS: in progress]\n")), "t.0", "Tab"
    )
    names = {u["style_name"] for u in plan["text_updates"]}
    assert {"badge", "key_concept"} <= names


# --- tablas ---------------------------------------------------------------

def test_distribute_widths_sums_exactly():
    widths = distribute_widths([], 3, 542.0)
    assert sum(widths) == pytest.approx(542.0, abs=0.05)


def test_distribute_widths_scales_proportionally():
    widths = distribute_widths([100.0, 200.0, 100.0], 3, 542.0)
    assert widths[1] > widths[0]
    assert sum(widths) == pytest.approx(542.0, abs=0.05)


def test_widths_conform_requires_fixed_width():
    props = [{"widthType": "FIXED_WIDTH", "width": {"magnitude": 271.0}}] * 2
    assert widths_conform(props, 2, 542.0, 542.0)
    assert not widths_conform(props, 2, 400.0, 542.0)
    props_evenly = [{"widthType": "EVENLY_DISTRIBUTED"}] * 2
    assert not widths_conform(props_evenly, 2, 542.0, 542.0)


# --- requests -------------------------------------------------------------

def test_build_requests_includes_tab_id(manifest):
    plan = StyleSyncEngine(manifest).analyze(
        _doc(_paragraph("2. Methodology\n", "HEADING_2")), "t.abc", "Tab"
    )
    requests = build_requests(plan, "t.abc")
    assert requests
    for req in requests:
        payload = next(iter(req.values()))
        if "range" in payload:
            assert payload["range"]["tabId"] == "t.abc"


def test_build_requests_omits_widths_when_guard_is_disabled(manifest):
    plan = {
        "table_updates": [{
            "table_index": 1, "start_index": 10, "rows": 2, "columns": 2,
            "target_widths": [271.0, 271.0], "pin_header": True,
            "header": {"row": 0, "bg": "#E6007E", "text_color": "#FFFFFF"},
            "zebra_rows": [], "summary_row": None, "cell_text_updates": [],
        }]
    }
    with_widths = build_requests(plan, "t.0", restore_table_widths=True)
    without_widths = build_requests(plan, "t.0", restore_table_widths=False)
    assert any("updateTableColumnProperties" in r for r in with_widths)
    assert not any("updateTableColumnProperties" in r for r in without_widths)
