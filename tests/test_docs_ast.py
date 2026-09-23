"""Tests for the Markdown-to-Docs-API request converter."""

import pytest

from gwork.sync.docs_ast import (
    Paragraph,
    Run,
    Table,
    UnsupportedNode,
    cell_text_requests,
    clear_body_requests,
    insert_requests,
    markdown_to_blocks,
    match_blocks,
    pandoc_ast_to_blocks,
    segment_blocks,
    style_requests,
    u16len,
)


def _doc_paragraph(text, start):
    return {
        "startIndex": start,
        "endIndex": start + u16len(text) + 1,
        "paragraph": {"paragraphStyle": {},
                      "elements": [{"textRun": {"content": text + "\n"}}]},
    }


# --- index arithmetic -----------------------------------------------------

def test_u16len_counts_units_not_characters():
    assert u16len("hello") == 5
    assert u16len("ñ") == 1          # BMP: one unit
    assert u16len("🌱") == 2         # surrogate pair: two units
    assert u16len("a🌱b") == 4


def test_run_offsets_use_utf16():
    block = Paragraph(runs=[Run(text="🌱 "), Run(text="sprout", bold=True)])
    doc = {"body": {"content": [_doc_paragraph(block.text, 1)]}}
    bold = [r for r in style_requests(doc, [block])
            if "updateTextStyle" in r and r["updateTextStyle"]["textStyle"]["bold"]]
    assert bold[0]["updateTextStyle"]["range"]["startIndex"] == 4   # 1 + 2 + 1


# --- Markdown conversion -------------------------------------------------

def test_headings_map_to_named_styles():
    blocks = markdown_to_blocks("# One\n\n## Two\n\n### Three\n")
    assert [b.named_style for b in blocks] == ["HEADING_1", "HEADING_2", "HEADING_3"]


def test_emphasis_and_links_become_runs():
    blocks = markdown_to_blocks("A **strong** word and a [link](https://ennui.solutions).\n")
    runs = blocks[0].runs
    assert any(r.bold and r.text == "strong" for r in runs)
    assert any(r.link == "https://ennui.solutions" for r in runs)


def test_adjacent_runs_with_same_style_merge():
    blocks = markdown_to_blocks("plain unformatted words\n")
    assert len(blocks[0].runs) == 1


def test_lists_mark_bullets_and_numbers():
    blocks = markdown_to_blocks("- one\n- two\n\n1. a\n2. b\n")
    assert [b.bullet for b in blocks] == ["bullet", "bullet", "number", "number"]


def test_blockquote_marks_quote():
    assert markdown_to_blocks("> a quote\n")[0].quote is True


def test_code_block_uses_one_paragraph_per_line():
    blocks = markdown_to_blocks("```\none\ntwo\n```\n")
    assert [b.text for b in blocks] == ["one", "two"]
    assert all(b.code for b in blocks)


def test_horizontal_rule_is_discarded():
    assert len(markdown_to_blocks("text\n\n---\n\nmore text\n")) == 2


def test_table_converts_with_header_and_body():
    table = markdown_to_blocks("| A | B |\n| --- | --- |\n| 1 | 2 |\n")[0]
    assert isinstance(table, Table)
    assert (table.num_rows, table.num_cols) == (2, 2)
    assert table.rows[0][0][0].text == "A"
    assert table.rows[1][1][0].text == "2"


def test_image_fails_loudly():
    with pytest.raises(UnsupportedNode):
        markdown_to_blocks("![chart](chart.png)\n")


def test_merged_cell_fails_loudly():
    ast = {"meta": {}, "blocks": [{"t": "Table", "c": [
        ["", [], []], [None, []], [],
        [["", [], []], [[["", [], []], [
            [["", [], []], {"t": "AlignDefault"}, 1, 2,
             [{"t": "Plain", "c": [{"t": "Str", "c": "x"}]}]]
        ]]]],
        [], [["", [], []], []],
    ]}]}
    with pytest.raises(UnsupportedNode):
        pandoc_ast_to_blocks(ast)


# --- phase 1: insertion ---------------------------------------------------

def test_segment_blocks_separates_text_and_tables():
    blocks = [Paragraph(runs=[Run(text="a")]), Table(rows=[[[Paragraph()]]]),
              Paragraph(runs=[Run(text="b")])]
    assert [kind for kind, _ in segment_blocks(blocks)] == ["text", "table", "text"]


def test_insert_requests_use_reverse_order_at_same_index():
    blocks = [Paragraph(runs=[Run(text="first")]),
              Table(rows=[[[Paragraph(runs=[Run(text="cell")])]]]),
              Paragraph(runs=[Run(text="last")])]
    requests = insert_requests(blocks, "t.0")
    assert requests[0]["insertText"]["text"] == "last\n"
    assert "insertTable" in requests[1]
    assert requests[2]["insertText"]["text"] == "first\n"
    payloads = [next(iter(r.values())) for r in requests]
    assert [p["location"]["index"] for p in payloads] == [1, 1, 1]
    assert all(p["location"]["tabId"] == "t.0" for p in payloads)


def test_clear_body_preserves_final_paragraph():
    doc = {"body": {"content": [{"endIndex": 1}, {"endIndex": 42}]}}
    text_range = clear_body_requests(doc)[0]["deleteContentRange"]["range"]
    assert (text_range["startIndex"], text_range["endIndex"]) == (1, 41)


def test_clear_body_emits_nothing_for_empty_document():
    assert clear_body_requests({"body": {"content": [{"endIndex": 1}]}}) == []


# --- matching and phases 2/3 ---------------------------------------------

def test_match_blocks_skips_empty_paragraphs_added_by_docs():
    blocks = [Paragraph(runs=[Run(text="before")]),
              Table(rows=[[[Paragraph(runs=[Run(text="c")])]]]),
              Paragraph(runs=[Run(text="after")])]
    doc = {"body": {"content": [
        _doc_paragraph("before", 1),
        _doc_paragraph("", 8),                      # Added by Docs.
        {"startIndex": 8, "endIndex": 20, "table": {"tableRows": []}},
        _doc_paragraph("after", 20),
    ]}}
    pairs = match_blocks(doc, blocks)
    assert [type(b).__name__ for b, _ in pairs] == ["Paragraph", "Table", "Paragraph"]


def test_match_blocks_fails_when_remote_does_not_match():
    with pytest.raises(RuntimeError):
        match_blocks({"body": {"content": []}}, [Paragraph(runs=[Run(text="x")])])


def test_cell_text_requests_run_from_last_cell_to_first():
    table = Table(rows=[[[Paragraph(runs=[Run(text="A")])],
                         [Paragraph(runs=[Run(text="B")])]]])
    doc = {"body": {"content": [{
        "startIndex": 1, "endIndex": 10,
        "table": {"tableRows": [{"tableCells": [
            {"content": [_doc_paragraph("", 3)]},
            {"content": [_doc_paragraph("", 5)]},
        ]}]},
    }]}}
    requests = cell_text_requests(doc, [table])
    indices = [r["insertText"]["location"]["index"] for r in requests]
    assert indices == sorted(indices, reverse=True)
    assert requests[0]["insertText"]["text"] == "B"


def test_style_requests_emit_named_style_and_bullets_last():
    blocks = [Paragraph(runs=[Run(text="Title")], named_style="HEADING_1"),
              Paragraph(runs=[Run(text="item")], bullet="bullet")]
    doc = {"body": {"content": [_doc_paragraph("Title", 1),
                                _doc_paragraph("item", 7)]}}
    requests = style_requests(doc, blocks)
    assert requests[0]["updateParagraphStyle"]["paragraphStyle"]["namedStyleType"] == "HEADING_1"
    assert "createParagraphBullets" in requests[-1]


def test_style_requests_carry_link():
    block = Paragraph(runs=[Run(text="record", link="https://ennui.solutions")])
    doc = {"body": {"content": [_doc_paragraph("record", 1)]}}
    links = [r for r in style_requests(doc, [block])
             if "updateTextStyle" in r and "link" in r["updateTextStyle"]["textStyle"]]
    assert links[0]["updateTextStyle"]["textStyle"]["link"]["url"] == "https://ennui.solutions"


def test_quote_receives_indent():
    block = Paragraph(runs=[Run(text="quote")], quote=True)
    doc = {"body": {"content": [_doc_paragraph("quote", 1)]}}
    style = style_requests(doc, [block])[0]["updateParagraphStyle"]
    assert style["paragraphStyle"]["indentStart"]["magnitude"] == 36.0
    assert "indentStart" in style["fields"]
