"""Tests de la siembra de namedStyles vía .docx."""

import re
import zipfile

import pytest

from cowork.style.commands import write_doc_id
from cowork.style.manifest import StyleManifest
from cowork.style.seed import build_reference_docx, build_styles_xml

BASE_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    "<w:docDefaults><w:rPrDefault><w:rPr>"
    '<w:rFonts w:asciiTheme="minorHAnsi"/><w:sz w:val="24"/>'
    "</w:rPr></w:rPrDefault></w:docDefaults>"
    '<w:style w:type="paragraph" w:default="1" w:styleId="Normal">'
    '<w:name w:val="Normal"/></w:style>'
    '<w:style w:type="paragraph" w:styleId="Heading1">'
    '<w:name w:val="heading 1"/><w:rPr><w:sz w:val="40"/></w:rPr></w:style>'
    '<w:style w:type="paragraph" w:styleId="Title">'
    '<w:name w:val="Title"/></w:style>'
    "</w:styles>"
)

MANIFEST_DATA = {
    "document": {"doc_id": "DOC"},
    "design_system": {
        "typography": {
            "font_family_primary": "Nunito",
            "scales": {
                "title": {"size": 24, "weight": 900, "alignment": "CENTER",
                          "color": "#000000", "space_below": 24},
                "heading_1": {"size": 18, "weight": 900, "color": "#E6007E",
                              "space_above": 18, "space_below": 7},
                "normal_text": {"size": 10, "weight": 400, "alignment": "JUSTIFIED",
                                "line_spacing": 100, "space_below": 6},
            },
        }
    },
}


@pytest.fixture
def manifest():
    return StyleManifest(MANIFEST_DATA)


def _style(xml, style_id):
    match = re.search(
        r'<w:style [^>]*w:styleId="%s"\s*>.*?</w:style>' % style_id, xml, re.S
    )
    assert match, f"no se encontró el estilo {style_id}"
    return match.group(0)


def test_normal_toma_fuente_tamano_y_alineacion(manifest):
    xml = build_styles_xml(BASE_XML, manifest)
    normal = _style(xml, "Normal")
    assert 'w:ascii="Nunito"' in normal
    assert 'w:sz w:val="20"' in normal          # 10pt → 20 medios puntos
    assert 'w:jc w:val="both"' in normal        # JUSTIFIED
    assert 'w:after="120"' in normal            # 6pt → 120 twips


def test_heading_1_lleva_color_y_outline(manifest):
    heading = _style(build_styles_xml(BASE_XML, manifest), "Heading1")
    assert 'w:color w:val="E6007E"' in heading
    assert 'w:sz w:val="36"' in heading
    assert 'w:outlineLvl w:val="0"' in heading


def test_weight_900_se_degrada_a_negrita_binaria(manifest):
    """Word no tiene pesos numéricos: 900 se importa como bold."""
    heading = _style(build_styles_xml(BASE_XML, manifest), "Heading1")
    assert "<w:b/>" in heading
    assert "900" not in heading


def test_doc_defaults_dejan_de_apuntar_al_tema(manifest):
    xml = build_styles_xml(BASE_XML, manifest)
    defaults = re.search(r"<w:rPrDefault>.*?</w:rPrDefault>", xml, re.S).group(0)
    assert "minorHAnsi" not in defaults
    assert 'w:ascii="Nunito"' in defaults


def test_estilo_ausente_en_la_base_se_agrega(manifest):
    xml = build_styles_xml(BASE_XML, manifest)
    assert 'w:styleId="BodyText"' in xml
    assert xml.rstrip().endswith("</w:styles>")


def test_scale_no_declarada_no_se_inventa(manifest):
    xml = build_styles_xml(BASE_XML, manifest)
    assert 'w:styleId="Heading5"' not in xml


def test_build_reference_docx_reempaqueta_el_zip(manifest, tmp_path):
    base = tmp_path / "base.docx"
    with zipfile.ZipFile(base, "w") as z:
        z.writestr("word/styles.xml", BASE_XML)
        z.writestr("word/document.xml", "<w:document/>")
    out = build_reference_docx(manifest, tmp_path / "out.docx", base_docx=base)
    with zipfile.ZipFile(out) as z:
        assert set(z.namelist()) == {"word/styles.xml", "word/document.xml"}
        assert 'w:ascii="Nunito"' in z.read("word/styles.xml").decode()
        assert z.read("word/document.xml").decode() == "<w:document/>"


def test_base_sin_styles_xml_falla(manifest, tmp_path):
    base = tmp_path / "vacio.docx"
    with zipfile.ZipFile(base, "w") as z:
        z.writestr("word/document.xml", "<w:document/>")
    with pytest.raises(RuntimeError):
        build_reference_docx(manifest, tmp_path / "out.docx", base_docx=base)


def test_write_doc_id_no_duplica_la_clave():
    assert write_doc_id("document:\n  doc_id: ''\n  title: x\n", "NUEVO") == (
        'document:\n  doc_id: "NUEVO"\n  title: x\n'
    )
    assert write_doc_id("document:\n  title: x\n", "NUEVO").count("doc_id") == 1
