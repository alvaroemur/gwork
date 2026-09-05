"""Tests del conversor Markdown → requests de la Docs API."""

import pytest

from cowork.sync.docs_ast import (
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


# --- aritmética de índices ------------------------------------------------

def test_u16len_cuenta_unidades_no_caracteres():
    assert u16len("hola") == 4
    assert u16len("ñ") == 1          # BMP: una unidad
    assert u16len("🌱") == 2         # par suplente: dos unidades
    assert u16len("a🌱b") == 4


def test_offsets_de_runs_usan_utf16():
    block = Paragraph(runs=[Run(text="🌱 "), Run(text="brote", bold=True)])
    doc = {"body": {"content": [_doc_paragraph(block.text, 1)]}}
    negrita = [r for r in style_requests(doc, [block])
               if "updateTextStyle" in r and r["updateTextStyle"]["textStyle"]["bold"]]
    assert negrita[0]["updateTextStyle"]["range"]["startIndex"] == 4   # 1 + 2 + 1


# --- conversión del Markdown ---------------------------------------------

def test_encabezados_mapean_a_named_style():
    blocks = markdown_to_blocks("# Uno\n\n## Dos\n\n### Tres\n")
    assert [b.named_style for b in blocks] == ["HEADING_1", "HEADING_2", "HEADING_3"]


def test_enfasis_y_enlaces_se_vuelven_runs():
    blocks = markdown_to_blocks("Un **fuerte** y un [enlace](https://ennui.solutions).\n")
    runs = blocks[0].runs
    assert any(r.bold and r.text == "fuerte" for r in runs)
    assert any(r.link == "https://ennui.solutions" for r in runs)


def test_runs_contiguos_del_mismo_estilo_se_fusionan():
    blocks = markdown_to_blocks("palabras sueltas sin formato\n")
    assert len(blocks[0].runs) == 1


def test_listas_marcan_vinetas_y_numeracion():
    blocks = markdown_to_blocks("- uno\n- dos\n\n1. a\n2. b\n")
    assert [b.bullet for b in blocks] == ["bullet", "bullet", "number", "number"]


def test_blockquote_marca_cita():
    assert markdown_to_blocks("> una cita\n")[0].quote is True


def test_code_block_una_linea_por_parrafo():
    blocks = markdown_to_blocks("```\nuno\ndos\n```\n")
    assert [b.text for b in blocks] == ["uno", "dos"]
    assert all(b.code for b in blocks)


def test_separador_horizontal_se_descarta():
    assert len(markdown_to_blocks("texto\n\n---\n\nmás texto\n")) == 2


def test_tabla_se_convierte_con_cabecera_y_cuerpo():
    table = markdown_to_blocks("| A | B |\n| --- | --- |\n| 1 | 2 |\n")[0]
    assert isinstance(table, Table)
    assert (table.num_rows, table.num_cols) == (2, 2)
    assert table.rows[0][0][0].text == "A"
    assert table.rows[1][1][0].text == "2"


def test_imagen_falla_ruidosamente():
    with pytest.raises(UnsupportedNode):
        markdown_to_blocks("![gráfico](grafico.png)\n")


def test_celda_combinada_falla_ruidosamente():
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


# --- fase 1: inserciones --------------------------------------------------

def test_segment_blocks_separa_texto_y_tablas():
    blocks = [Paragraph(runs=[Run(text="a")]), Table(rows=[[[Paragraph()]]]),
              Paragraph(runs=[Run(text="b")])]
    assert [kind for kind, _ in segment_blocks(blocks)] == ["text", "table", "text"]


def test_insert_requests_van_en_orden_inverso_al_mismo_indice():
    blocks = [Paragraph(runs=[Run(text="primero")]),
              Table(rows=[[[Paragraph(runs=[Run(text="celda")])]]]),
              Paragraph(runs=[Run(text="último")])]
    requests = insert_requests(blocks, "t.0")
    assert requests[0]["insertText"]["text"] == "último\n"
    assert "insertTable" in requests[1]
    assert requests[2]["insertText"]["text"] == "primero\n"
    payloads = [next(iter(r.values())) for r in requests]
    assert [p["location"]["index"] for p in payloads] == [1, 1, 1]
    assert all(p["location"]["tabId"] == "t.0" for p in payloads)


def test_clear_body_conserva_el_parrafo_final():
    doc = {"body": {"content": [{"endIndex": 1}, {"endIndex": 42}]}}
    rango = clear_body_requests(doc)[0]["deleteContentRange"]["range"]
    assert (rango["startIndex"], rango["endIndex"]) == (1, 41)


def test_clear_body_de_documento_vacio_no_emite_nada():
    assert clear_body_requests({"body": {"content": [{"endIndex": 1}]}}) == []


# --- emparejamiento y fases 2/3 ------------------------------------------

def test_match_blocks_saltea_parrafos_vacios_que_agrega_docs():
    blocks = [Paragraph(runs=[Run(text="antes")]),
              Table(rows=[[[Paragraph(runs=[Run(text="c")])]]]),
              Paragraph(runs=[Run(text="después")])]
    doc = {"body": {"content": [
        _doc_paragraph("antes", 1),
        _doc_paragraph("", 7),                      # el que agrega Docs
        {"startIndex": 8, "endIndex": 20, "table": {"tableRows": []}},
        _doc_paragraph("después", 20),
    ]}}
    pares = match_blocks(doc, blocks)
    assert [type(b).__name__ for b, _ in pares] == ["Paragraph", "Table", "Paragraph"]


def test_match_blocks_falla_si_el_remoto_no_coincide():
    with pytest.raises(RuntimeError):
        match_blocks({"body": {"content": []}}, [Paragraph(runs=[Run(text="x")])])


def test_cell_text_requests_van_de_la_ultima_celda_a_la_primera():
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


def test_style_requests_emiten_named_style_y_vinetas_al_final():
    blocks = [Paragraph(runs=[Run(text="Título")], named_style="HEADING_1"),
              Paragraph(runs=[Run(text="ítem")], bullet="bullet")]
    doc = {"body": {"content": [_doc_paragraph("Título", 1),
                                _doc_paragraph("ítem", 9)]}}
    requests = style_requests(doc, blocks)
    assert requests[0]["updateParagraphStyle"]["paragraphStyle"]["namedStyleType"] == "HEADING_1"
    assert "createParagraphBullets" in requests[-1]


def test_style_requests_transportan_el_enlace():
    block = Paragraph(runs=[Run(text="ficha", link="https://ennui.solutions")])
    doc = {"body": {"content": [_doc_paragraph("ficha", 1)]}}
    enlaces = [r for r in style_requests(doc, [block])
               if "updateTextStyle" in r and "link" in r["updateTextStyle"]["textStyle"]]
    assert enlaces[0]["updateTextStyle"]["textStyle"]["link"]["url"] == "https://ennui.solutions"


def test_cita_recibe_sangria():
    block = Paragraph(runs=[Run(text="cita")], quote=True)
    doc = {"body": {"content": [_doc_paragraph("cita", 1)]}}
    style = style_requests(doc, [block])[0]["updateParagraphStyle"]
    assert style["paragraphStyle"]["indentStart"]["magnitude"] == 36.0
    assert "indentStart" in style["fields"]
