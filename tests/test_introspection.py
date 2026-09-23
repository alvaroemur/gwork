from pathlib import Path

import yaml

from gwork.style.commands import refresh_template
from gwork.style.introspect import extract_style_tokens, template_markdown
from gwork.style.engine import StyleSyncEngine
from gwork.style.manifest import StyleManifest
from gwork.sync.manifest import load_manifest


def _rgb(hex_value: str) -> dict:
    value = hex_value.lstrip("#")
    return {
        "rgbColor": {
            "red": int(value[0:2], 16) / 255,
            "green": int(value[2:4], 16) / 255,
            "blue": int(value[4:6], 16) / 255,
        }
    }


def _paragraph(text: str, named_style: str, start: int, text_style=None, paragraph_style=None):
    end = start + len(text)
    style = {"namedStyleType": named_style, **(paragraph_style or {})}
    return {
        "startIndex": start,
        "endIndex": end,
        "paragraph": {
            "paragraphStyle": style,
            "elements": [{
                "startIndex": start,
                "endIndex": end,
                "textRun": {
                    "content": text,
                    "textStyle": text_style or {},
                },
            }],
        },
    }


def test_extracts_heading_callout_inline_code_and_table_tokens():
    heading = _paragraph(
        "Scope\n",
        "HEADING_1",
        1,
        text_style={
            "weightedFontFamily": {"fontFamily": "Inter"},
            "fontSize": {"magnitude": 18},
            "foregroundColor": _rgb("#123456"),
            "bold": True,
        },
    )
    eyebrow = _paragraph(
        "PROJECT BRIEF\n",
        "NORMAL_TEXT",
        7,
        text_style={
            "weightedFontFamily": {"fontFamily": "Inter"},
            "fontSize": {"magnitude": 9},
            "foregroundColor": _rgb("#654321"),
            "bold": True,
        },
    )
    callout = _paragraph(
        "Important note\n",
        "NORMAL_TEXT",
        21,
        paragraph_style={
            "shading": {"backgroundColor": _rgb("#F0F0F0")},
            "borderLeft": {
                "color": _rgb("#123456"),
                "width": {"magnitude": 3},
                "dashStyle": "SOLID",
            },
        },
    )
    code = _paragraph(
        "gwork sync\n",
        "NORMAL_TEXT",
        37,
        text_style={
            "weightedFontFamily": {"fontFamily": "Roboto Mono"},
            "backgroundColor": _rgb("#EEEEEE"),
            "foregroundColor": _rgb("#222222"),
        },
    )
    table = {
        "startIndex": 49,
        "table": {
            "rows": 1,
            "columns": 1,
            "tableRows": [{
                "tableCells": [{
                    "tableCellStyle": {"backgroundColor": _rgb("#123456")},
                    "content": [_paragraph(
                        "Header\n",
                        "NORMAL_TEXT",
                        51,
                        text_style={"foregroundColor": _rgb("#FFFFFF")},
                    )],
                }],
            }],
        },
    }
    raw = {
        "documentStyle": {
            "pageSize": {"width": {"magnitude": 612}},
            "marginLeft": {"magnitude": 36},
            "marginRight": {"magnitude": 36},
        },
        "body": {"content": [heading, eyebrow, callout, code, table]},
    }

    tokens = extract_style_tokens([raw])

    assert tokens["typography"]["heading_1"]["font"] == "Inter"
    assert tokens["typography"]["heading_1"]["size"] == 18
    assert tokens["components"]["eyebrow"]["size"] == 9
    assert tokens["components"]["callout"]["background"] == "#F0F0F0"
    assert tokens["components"]["inline_code"]["font"] == "Roboto Mono"
    assert tokens["components"]["tables"]["header_background"] == "#123456"
    assert tokens["page_layout"]["printable_width"] == 540


def test_template_markdown_contains_each_visual_specimen():
    markdown = template_markdown({})
    assert "EYEBROW" in markdown
    assert "## Heading 1" in markdown
    assert "> 💡 Callout sample" in markdown
    assert "`code sample`" in markdown
    assert "| Header A | Header B |" in markdown


def test_engine_applies_extracted_eyebrow_token():
    manifest = StyleManifest({
        "style": {
            "tokens": {
                "typography": {"font_family_primary": "Inter"},
                "components": {
                    "eyebrow": {
                        "font": "Inter",
                        "size": 9,
                        "color": "#654321",
                        "weight": 700,
                    },
                },
            },
        },
    })
    raw = {
        "documentStyle": {},
        "body": {"content": [_paragraph("PROJECT BRIEF\n", "NORMAL_TEXT", 1)]},
    }

    plan = StyleSyncEngine(manifest).analyze(raw, "tab", "_template")

    eyebrow = next(item for item in plan["text_updates"] if item["style_name"] == "eyebrow")
    assert eyebrow["size"] == 9
    assert eyebrow["bold"] is True


def test_unified_manifest_supplies_transport_items_and_style(tmp_path: Path):
    path = tmp_path / ".gwork.yaml"
    path.write_text(
        yaml.safe_dump({
            "version": 1,
            "transport": {"provider": "gog", "account": "user@example.com"},
            "items": [{
                "local": "docs/spec.md",
                "drive_id": "DOC",
                "type": "doc",
                "content_mode": "ast",
            }],
            "style": {
                "template_tab": "_template",
                "tokens": {"typography": {"heading_1": {"size": 18}}},
            },
        }),
        encoding="utf-8",
    )

    manifest = load_manifest(tmp_path)
    style = StyleManifest.load(path)

    assert manifest.transport.account == "user@example.com"
    assert manifest.account_for_gog() == "user@example.com"
    assert manifest.account_for_gog("override@example.com") == "override@example.com"
    assert manifest.effective_content_mode(manifest.items[0]) == "ast"
    assert style.doc_id == "DOC"
    assert style.account == "user@example.com"
    assert style.scales["heading_1"]["size"] == 18


def test_writing_tokens_preserves_transport_and_items(tmp_path: Path):
    path = tmp_path / ".gwork.yaml"
    path.write_text(
        "version: 1\n"
        "transport:\n"
        "  provider: gog\n"
        "items:\n"
        "  - local: spec.md\n"
        "    drive_id: DOC\n"
        "    type: doc\n"
        "style:\n"
        "  template_tab: _template\n",
        encoding="utf-8",
    )
    manifest = StyleManifest.load(path)
    manifest.write_tokens({"typography": {"heading_1": {"size": 18}}}, "tab-template")

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["transport"]["provider"] == "gog"
    assert data["items"][0]["local"] == "spec.md"
    assert data["style"]["template_tab_id"] == "tab-template"
    assert data["style"]["tokens"]["typography"]["heading_1"]["size"] == 18


def test_refresh_template_creates_tab_writes_specimen_and_persists_tokens(
    tmp_path: Path,
    monkeypatch,
):
    path = tmp_path / ".gwork.yaml"
    path.write_text(
        "version: 1\n"
        "transport:\n"
        "  provider: gog\n"
        "items:\n"
        "  - local: spec.md\n"
        "    drive_id: DOC\n"
        "    type: doc\n"
        "style:\n"
        "  template_tab: _template\n",
        encoding="utf-8",
    )
    manifest = StyleManifest.load(path)
    raw = {
        "documentStyle": {},
        "body": {
            "content": [
                _paragraph(
                    "Design token template\n",
                    "TITLE",
                    1,
                    text_style={
                        "weightedFontFamily": {"fontFamily": "Inter"},
                        "fontSize": {"magnitude": 24},
                    },
                ),
                _paragraph(
                    "Scope\n",
                    "HEADING_1",
                    23,
                    text_style={
                        "weightedFontFamily": {"fontFamily": "Inter"},
                        "fontSize": {"magnitude": 18},
                    },
                ),
            ],
        },
    }
    writes = []
    batches = []
    monkeypatch.setattr(
        "gwork.style.commands.gog.docs_list_tabs",
        lambda doc_id, account: [{"id": "source", "title": "Main"}],
    )
    monkeypatch.setattr(
        "gwork.style.commands.gog.docs_add_tab",
        lambda doc_id, title, account: {"tab": {"id": "template"}},
    )
    monkeypatch.setattr(
        "gwork.style.commands.gog.docs_raw",
        lambda doc_id, tab_id, account: raw,
    )
    monkeypatch.setattr(
        "gwork.style.commands.gog.docs_write_markdown",
        lambda doc_id, tab, markdown_path, account: writes.append(
            (doc_id, tab, markdown_path.read_text(encoding="utf-8"))
        ),
    )
    monkeypatch.setattr(
        "gwork.style.commands.gog.batch_execute",
        lambda doc_id, requests, account, source: batches.append(
            (doc_id, requests, source)
        ),
    )

    result = refresh_template(manifest, "user@example.com")

    assert result["template_tab_id"] == "template"
    assert writes[0][0:2] == ("DOC", "template")
    assert "Design token template" in writes[0][2]
    assert batches[0][2] == "gwork.style.template"
    persisted = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert persisted["style"]["tokens"]["typography"]["heading_1"]["font"] == "Inter"
