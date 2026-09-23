"""Tests for seeding namedStyles through .docx."""

import re
import zipfile

import pytest
import yaml

from gwork.style.commands import write_doc_id
from gwork.style.manifest import StyleManifest
from gwork.style.seed import build_reference_docx, build_styles_xml

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
    "style": {
        "document_id": "DOC",
        "tokens": {
            "typography": {
                "font_family_primary": "Nunito",
                "title": {"size": 24, "weight": 900, "alignment": "CENTER",
                          "color": "#000000", "space_below": 24},
                "heading_1": {"size": 18, "weight": 900, "color": "#E6007E",
                              "space_above": 18, "space_below": 7},
                "normal_text": {"size": 10, "weight": 400, "alignment": "JUSTIFIED",
                                "line_spacing": 100, "space_below": 6},
            },
        },
    },
}


@pytest.fixture
def manifest():
    return StyleManifest(MANIFEST_DATA)


def _style(xml, style_id):
    match = re.search(
        r'<w:style [^>]*w:styleId="%s"\s*>.*?</w:style>' % style_id, xml, re.S
    )
    assert match, f"style not found: {style_id}"
    return match.group(0)


def test_normal_uses_font_size_and_alignment(manifest):
    xml = build_styles_xml(BASE_XML, manifest)
    normal = _style(xml, "Normal")
    assert 'w:ascii="Nunito"' in normal
    assert 'w:sz w:val="20"' in normal          # 10pt → 20 half-points
    assert 'w:jc w:val="both"' in normal        # JUSTIFIED
    assert 'w:after="120"' in normal            # 6pt → 120 twips


def test_heading_1_has_color_and_outline(manifest):
    heading = _style(build_styles_xml(BASE_XML, manifest), "Heading1")
    assert 'w:color w:val="E6007E"' in heading
    assert 'w:sz w:val="36"' in heading
    assert 'w:outlineLvl w:val="0"' in heading


def test_weight_900_degrades_to_binary_bold(manifest):
    """Word has no numeric weights, so 900 imports as bold."""
    heading = _style(build_styles_xml(BASE_XML, manifest), "Heading1")
    assert "<w:b/>" in heading
    assert "900" not in heading


def test_doc_defaults_stop_referencing_theme(manifest):
    xml = build_styles_xml(BASE_XML, manifest)
    defaults = re.search(r"<w:rPrDefault>.*?</w:rPrDefault>", xml, re.S).group(0)
    assert "minorHAnsi" not in defaults
    assert 'w:ascii="Nunito"' in defaults


def test_missing_base_style_is_added(manifest):
    xml = build_styles_xml(BASE_XML, manifest)
    assert 'w:styleId="BodyText"' in xml
    assert xml.rstrip().endswith("</w:styles>")


def test_undeclared_scale_is_not_invented(manifest):
    xml = build_styles_xml(BASE_XML, manifest)
    assert 'w:styleId="Heading5"' not in xml


def test_build_reference_docx_repacks_zip(manifest, tmp_path):
    base = tmp_path / "base.docx"
    with zipfile.ZipFile(base, "w") as z:
        z.writestr("word/styles.xml", BASE_XML)
        z.writestr("word/document.xml", "<w:document/>")
    out = build_reference_docx(manifest, tmp_path / "out.docx", base_docx=base)
    with zipfile.ZipFile(out) as z:
        assert set(z.namelist()) == {"word/styles.xml", "word/document.xml"}
        assert 'w:ascii="Nunito"' in z.read("word/styles.xml").decode()
        assert z.read("word/document.xml").decode() == "<w:document/>"


def test_base_without_styles_xml_fails(manifest, tmp_path):
    base = tmp_path / "empty.docx"
    with zipfile.ZipFile(base, "w") as z:
        z.writestr("word/document.xml", "<w:document/>")
    with pytest.raises(RuntimeError):
        build_reference_docx(manifest, tmp_path / "out.docx", base_docx=base)


def test_write_doc_id_does_not_duplicate_key():
    original = "version: 1\ntransport:\n  provider: gog\nitems: []\nstyle:\n  document_id: OLD\n"
    updated = yaml.safe_load(write_doc_id(original, "NEW"))
    assert updated["style"]["document_id"] == "NEW"
    assert updated["transport"]["provider"] == "gog"
    assert "doc_id" not in updated.get("document", {})
