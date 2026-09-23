from __future__ import annotations

"""Seed ``namedStyles`` in a new Google Doc.

The Docs API does not expose ``updateNamedStyles``. Named styles can be read
through ``documents.get`` but not written through ``batchUpdate``, which returns
``Unknown name "updateNamedStyles"``. The API cannot redefine Heading 1 in an
existing document. Instead, import a ``.docx`` whose Word styles already contain
the tokens when creating the document.

Known limit: Word supports only binary bold. A manifest ``weight: 900`` imports
as ``weight=400`` plus bold. The exact numeric weight still requires an explicit
``gwork style apply`` overlay.
"""

import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Optional

from ..sync.gog import drive_upload
from .manifest import StyleManifest
from .tokens import is_bold_weight, parse_pt

# Manifest scale to Word styleId in the pandoc reference document.
SCALE_TO_WORD_STYLE = {
    "title": "Title",
    "subtitle": "Subtitle",
    "heading_1": "Heading1",
    "heading_2": "Heading2",
    "heading_3": "Heading3",
    "heading_4": "Heading4",
    "heading_5": "Heading5",
    "heading_6": "Heading6",
}

WORD_STYLE_NAMES = {
    "Title": "Title",
    "Subtitle": "Subtitle",
    "Heading1": "heading 1",
    "Heading2": "heading 2",
    "Heading3": "heading 3",
    "Heading4": "heading 4",
    "Heading5": "heading 5",
    "Heading6": "heading 6",
}

OUTLINE_LEVEL = {
    "Heading1": 0, "Heading2": 1, "Heading3": 2,
    "Heading4": 3, "Heading5": 4, "Heading6": 5,
}

ALIGNMENT_TO_WORD = {
    "CENTER": "center",
    "JUSTIFIED": "both",
    "START": "left",
    "LEFT": "left",
    "END": "right",
    "RIGHT": "right",
}

# Exercise each style so the imported Doc materializes it.
DEFAULT_SKELETON = """% {title}

# Level 1 heading

Reference body text that sets the document's base typography.

## Level 2 heading

### Level 3 heading

#### Level 4 heading
"""


def _twips(pt_value) -> int:
    return int(round(parse_pt(pt_value) * 20))


def _half_points(size) -> int:
    return int(round(float(size) * 2))


def _hex(color: Optional[str], default: str = "000000") -> str:
    if not color:
        return default
    return str(color).strip().lstrip("#").upper()


def _run_props(font: str, rule: dict, default_color: str = "000000") -> str:
    size = rule.get("size")
    bits = ['<w:rFonts w:ascii="%s" w:hAnsi="%s" w:cs="%s"/>' % (font, font, font)]
    if is_bold_weight(rule.get("weight", 400)):
        bits.append("<w:b/><w:bCs/>")
    bits.append('<w:color w:val="%s"/>' % _hex(rule.get("color"), default_color))
    if size:
        hp = _half_points(size)
        bits.append('<w:sz w:val="%d"/><w:szCs w:val="%d"/>' % (hp, hp))
    return "<w:rPr>" + "".join(bits) + "</w:rPr>"


def _par_props(rule: dict, outline: Optional[int] = None) -> str:
    bits = []
    alignment = ALIGNMENT_TO_WORD.get(str(rule.get("alignment", "")).upper())
    if alignment:
        bits.append('<w:jc w:val="%s"/>' % alignment)
    before = _twips(rule.get("space_above", 0))
    after = _twips(rule.get("space_below", 0))
    line = int(round(float(rule.get("line_spacing", 100)) / 100.0 * 240))
    bits.append(
        '<w:spacing w:before="%d" w:after="%d" w:line="%d" w:lineRule="auto"/>'
        % (before, after, line)
    )
    if outline is not None:
        bits.append('<w:outlineLvl w:val="%d"/>' % outline)
    return "<w:pPr>" + "".join(bits) + "</w:pPr>"


def _style_block(style_id: str, name: str, based_on: str, rule: dict,
                 font: str, outline: Optional[int] = None,
                 default: bool = False) -> str:
    default_attr = ' w:default="1"' if default else ""
    based = '<w:basedOn w:val="%s"/>' % based_on if based_on else ""
    return (
        '<w:style w:type="paragraph"%s w:styleId="%s">'
        '<w:name w:val="%s"/>%s<w:qFormat/>%s%s</w:style>'
        % (default_attr, style_id, name, based,
           _par_props(rule, outline), _run_props(font, rule))
    )


def _replace_style(xml: str, style_id: str, block: str) -> str:
    pattern = re.compile(
        r'<w:style [^>]*w:styleId="%s"\s*>.*?</w:style>' % re.escape(style_id), re.S
    )
    if pattern.search(xml):
        return pattern.sub(lambda _: block, xml, count=1)
    return xml.replace("</w:styles>", block + "</w:styles>")


def build_styles_xml(base_xml: str, manifest: StyleManifest) -> str:
    """Rewrite ``word/styles.xml`` with manifest tokens."""
    font = manifest.font_primary
    scales = manifest.scales
    normal_rule = scales.get("normal_text", {"size": 11, "weight": 400})

    xml = base_xml
    xml = _replace_style(
        xml, "Normal",
        _style_block("Normal", "Normal", "", normal_rule, font, default=True),
    )
    for body_id, body_name in (("BodyText", "Body Text"),
                               ("FirstParagraph", "First Paragraph"),
                               ("Compact", "Compact")):
        xml = _replace_style(
            xml, body_id, _style_block(body_id, body_name, "Normal", normal_rule, font)
        )

    for scale_key, style_id in SCALE_TO_WORD_STYLE.items():
        rule = scales.get(scale_key)
        if not rule:
            continue
        xml = _replace_style(
            xml, style_id,
            _style_block(style_id, WORD_STYLE_NAMES[style_id], "Normal", rule, font,
                         outline=OUTLINE_LEVEL.get(style_id)),
        )

    # docDefaults: a theme font would make Docs import Calibri.
    hp = _half_points(normal_rule.get("size", 11))
    xml = re.sub(
        r"<w:rPrDefault>.*?</w:rPrDefault>",
        lambda _: (
            "<w:rPrDefault><w:rPr>"
            '<w:rFonts w:ascii="%s" w:hAnsi="%s" w:cs="%s"/>'
            '<w:sz w:val="%d"/><w:szCs w:val="%d"/>'
            "</w:rPr></w:rPrDefault>" % (font, font, font, hp, hp)
        ),
        xml,
        count=1,
        flags=re.S,
    )
    return xml


def pandoc_reference_docx(out_path: Path) -> Path:
    """Copy pandoc's default reference.docx."""
    result = subprocess.run(
        ["pandoc", "--print-default-data-file", "reference.docx"],
        capture_output=True, check=True,
    )
    out_path.write_bytes(result.stdout)
    return out_path


def build_reference_docx(manifest: StyleManifest, out_path: Path,
                         base_docx: Optional[Path] = None) -> Path:
    """Build a pandoc reference document with manifest styles injected."""
    out_path = Path(out_path)
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(base_docx) if base_docx else pandoc_reference_docx(Path(tmp) / "ref.docx")
        with zipfile.ZipFile(base) as zin:
            entries = [(i, zin.read(i.filename)) for i in zin.infolist()]
        styles = None
        for info, payload in entries:
            if info.filename == "word/styles.xml":
                styles = payload.decode("utf-8")
        if styles is None:
            raise RuntimeError("%s does not contain word/styles.xml" % base)
        patched = build_styles_xml(styles, manifest)
        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zout:
            for info, payload in entries:
                if info.filename == "word/styles.xml":
                    zout.writestr(info.filename, patched.encode("utf-8"))
                else:
                    zout.writestr(info.filename, payload)
    return out_path


def markdown_to_docx(md_path: Path, reference_docx: Path, out_path: Path) -> Path:
    subprocess.run(
        ["pandoc", str(md_path), "-o", str(out_path),
         "--reference-doc=%s" % reference_docx],
        capture_output=True, check=True,
    )
    return Path(out_path)


def seed_document(manifest: StyleManifest, title: str,
                  md_path: Optional[Path] = None,
                  parent: Optional[str] = None,
                  account: Optional[str] = None,
                  keep_dir: Optional[Path] = None) -> dict:
    """Create a Google Doc whose ``namedStyles`` match the manifest."""
    workdir = Path(keep_dir) if keep_dir else Path(tempfile.mkdtemp(prefix="gwork-style-"))
    workdir.mkdir(parents=True, exist_ok=True)
    try:
        reference = build_reference_docx(manifest, workdir / "reference.docx")
        source = Path(md_path) if md_path else workdir / "skeleton.md"
        if md_path is None:
            source.write_text(DEFAULT_SKELETON.format(title=title), encoding="utf-8")
        docx = markdown_to_docx(source, reference, workdir / "seed.docx")
        return drive_upload(str(docx), parent=parent, name=title,
                            account=account, convert=True)
    finally:
        if keep_dir is None:
            shutil.rmtree(workdir, ignore_errors=True)
