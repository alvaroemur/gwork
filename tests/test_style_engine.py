"""Tests del motor de estilos: tokens, jerarquía, tablas y requests."""

import pytest

from cowork.style.engine import (
    StyleSyncEngine,
    distribute_widths,
    widths_conform,
)
from cowork.style.manifest import StyleManifest
from cowork.style.requests_builder import build_requests
from cowork.style.tokens import (
    colors_match,
    hex_to_rgb,
    is_bold_weight,
    parse_border,
    parse_pt,
    rgb_to_hex,
)


MANIFEST_DATA = {
    "document": {"doc_id": "DOC", "account": "quien@ejemplo.com"},
    "design_system": {
        "page_layout": {
            "size": "Letter",
            "margins": {"top": "35pt", "bottom": "35pt", "left": "35pt", "right": "35pt"},
            "printable_width": 542,
        },
        "typography": {
            "font_family_primary": "Nunito",
            "font_family_code": "Courier New",
            "scales": {
                "heading_1": {"size": 18, "weight": 900, "color": "#E6007E",
                              "space_above": 18, "space_below": 7},
                "heading_2": {"size": 14, "weight": 900, "color": "#000000"},
                "heading_3": {"size": 12, "weight": 900, "color": "#6A3FA0",
                              "border_bottom": "1.25pt solid #E6007E"},
                "normal_text": {"size": 10, "weight": 400, "alignment": "JUSTIFIED",
                                "space_below": 6},
            },
        },
        "colors": {"table_header_bg": "#E6007E", "secondary": "#6A3FA0"},
        "components": {"key_concepts": {"terms": ["bioeconomía"]}},
    },
    "sync_guards": {"remove_dash_dividers": True},
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

def test_hex_to_rgb_admite_forma_corta():
    assert hex_to_rgb("#FFF") == {"red": 1.0, "green": 1.0, "blue": 1.0}
    assert hex_to_rgb("#000000") == {"red": 0.0, "green": 0.0, "blue": 0.0}


def test_hex_rgb_ida_y_vuelta():
    assert rgb_to_hex(hex_to_rgb("#E6007E")) == "#E6007E"


def test_parse_pt_acepta_numero_y_cadena():
    assert parse_pt(12) == 12.0
    assert parse_pt("3.5pt") == 3.5
    assert parse_pt(None) == 0.0
    assert parse_pt("ancho") == 0.0


def test_parse_border_completo():
    assert parse_border("1.25pt solid #E6007E") == (1.25, "SOLID", "#E6007E")
    assert parse_border("2pt dashed #000")[1] == "DASH"
    assert parse_border(None) == (1.0, "SOLID", "#000000")


def test_colors_match_con_tolerancia():
    assert colors_match("#E6007E", hex_to_rgb("#E6007E"))
    assert not colors_match("#E6007E", hex_to_rgb("#000000"))
    assert not colors_match("#E6007E", None)


def test_is_bold_weight():
    assert is_bold_weight(900)
    assert is_bold_weight(700)
    assert not is_bold_weight(400)
    assert not is_bold_weight(None)


# --- jerarquía ------------------------------------------------------------

def test_heading_numerado_se_promueve(manifest):
    plan = StyleSyncEngine(manifest).analyze(
        _doc(_paragraph("2. Metodología\n", "HEADING_2")), "t.0", "Tab"
    )
    update = plan["paragraph_updates"][0]
    assert update["paragraphStyle"]["namedStyleType"] == "HEADING_1"
    assert update["style_name"] == "heading_1"


def test_normal_text_numerado_se_reconoce_como_heading(manifest):
    plan = StyleSyncEngine(manifest).analyze(
        _doc(_paragraph("3.1 Alcance\n", "NORMAL_TEXT")), "t.0", "Tab"
    )
    assert plan["paragraph_updates"][0]["paragraphStyle"]["namedStyleType"] == "HEADING_2"


def test_heading_3_recibe_borde_inferior(manifest):
    plan = StyleSyncEngine(manifest).analyze(
        _doc(_paragraph("Criterios\n", "HEADING_3")), "t.0", "Tab"
    )
    border = plan["paragraph_updates"][0]["paragraphStyle"]["borderBottom"]
    assert border["width"] == {"magnitude": 1.25, "unit": "PT"}
    assert border["color"]["color"]["rgbColor"] == hex_to_rgb("#E6007E")


def test_separador_de_guiones_se_marca_para_purga(manifest):
    plan = StyleSyncEngine(manifest).analyze(
        _doc(_paragraph("--------------------\n")), "t.0", "Tab"
    )
    assert len(plan["dividers_to_remove"]) == 1
    assert plan["paragraph_updates"] == []


def test_margen_fuera_de_tolerancia_se_audita(manifest):
    plan = StyleSyncEngine(manifest).analyze(_doc(margins=72.0), "t.0", "Tab")
    assert sum(1 for i in plan["audit_issues"] if i.startswith("Margen")) == 4


def test_enlace_de_usuario_se_preserva(manifest):
    element = _paragraph("ver la ficha\n")
    element["paragraph"]["elements"][0]["textRun"]["textStyle"] = {
        "link": {"url": "https://ejemplo.com"}
    }
    plan = StyleSyncEngine(manifest).analyze(_doc(element), "t.0", "Tab")
    assert plan["links_preserved"][0]["url"] == "https://ejemplo.com"


def test_callout_por_indentacion(manifest):
    element = _paragraph("Texto sangrado del bloque citado\n",
                         style={"indentStart": {"magnitude": 36.0}})
    plan = StyleSyncEngine(manifest).analyze(_doc(element), "t.0", "Tab")
    assert len(plan["callout_updates"]) == 1
    assert plan["callout_updates"][0]["indent_start"] == 12.0


def test_badge_y_concepto_clave_generan_rangos(manifest):
    plan = StyleSyncEngine(manifest).analyze(
        _doc(_paragraph("La bioeconomía avanza [ESTADO: en curso]\n")), "t.0", "Tab"
    )
    nombres = {u["style_name"] for u in plan["text_updates"]}
    assert {"badge", "key_concept"} <= nombres


# --- tablas ---------------------------------------------------------------

def test_distribute_widths_suma_exacta():
    widths = distribute_widths([], 3, 542.0)
    assert sum(widths) == pytest.approx(542.0, abs=0.05)


def test_distribute_widths_escala_proporcionalmente():
    widths = distribute_widths([100.0, 200.0, 100.0], 3, 542.0)
    assert widths[1] > widths[0]
    assert sum(widths) == pytest.approx(542.0, abs=0.05)


def test_widths_conform_exige_fixed_width():
    props = [{"widthType": "FIXED_WIDTH", "width": {"magnitude": 271.0}}] * 2
    assert widths_conform(props, 2, 542.0, 542.0)
    assert not widths_conform(props, 2, 400.0, 542.0)
    props_evenly = [{"widthType": "EVENLY_DISTRIBUTED"}] * 2
    assert not widths_conform(props_evenly, 2, 542.0, 542.0)


# --- requests -------------------------------------------------------------

def test_build_requests_incluye_tab_id(manifest):
    plan = StyleSyncEngine(manifest).analyze(
        _doc(_paragraph("2. Metodología\n", "HEADING_2")), "t.abc", "Tab"
    )
    requests = build_requests(plan, "t.abc")
    assert requests
    for req in requests:
        payload = next(iter(req.values()))
        if "range" in payload:
            assert payload["range"]["tabId"] == "t.abc"


def test_build_requests_omite_anchos_si_el_guard_esta_apagado(manifest):
    plan = {
        "table_updates": [{
            "table_index": 1, "start_index": 10, "rows": 2, "columns": 2,
            "target_widths": [271.0, 271.0], "pin_header": True,
            "header": {"row": 0, "bg": "#E6007E", "text_color": "#FFFFFF"},
            "zebra_rows": [], "summary_row": None, "cell_text_updates": [],
        }]
    }
    con = build_requests(plan, "t.0", restore_table_widths=True)
    sin = build_requests(plan, "t.0", restore_table_widths=False)
    assert any("updateTableColumnProperties" in r for r in con)
    assert not any("updateTableColumnProperties" in r for r in sin)
