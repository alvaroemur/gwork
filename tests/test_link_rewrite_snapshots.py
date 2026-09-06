"""Tests de link rewriting y snapshots de apply."""

from pathlib import Path

import yaml

from cowork.sync.manifest import Item, Manifest, load_manifest
from cowork.sync.snapshots import save_doc_apply_snapshot, snapshot_dir
from cowork.sync.transforms import apply_md_transforms, doc_transform_names, rewrite_links


def _manifest(root: Path, link_mode: str = "rewrite_to_drive") -> Manifest:
    return Manifest(
        client="test",
        drive_folder_id=None,
        root=root,
        link_mode=link_mode,
        items=[
            Item(
                local="docs/a.md",
                drive_id="DOC_A",
                type="doc",
            ),
            Item(
                local="docs/b.md",
                drive_id="DOC_B",
                type="doc",
            ),
            Item(
                local="docs/data.csv",
                drive_id="SHEET_1",
                type="sheet",
                sheet_tab="tab",
            ),
        ],
    )


def test_rewrite_links_resolves_relative_md_and_csv(tmp_path: Path):
    root = tmp_path
    (root / "docs").mkdir()
    (root / "docs" / "a.md").write_text(
        "Ver [otro doc](b.md) y [sheet](data.csv).\n",
        encoding="utf-8",
    )
    manifest = _manifest(root)
    text, n, unresolved = rewrite_links(
        (root / "docs" / "a.md").read_text(encoding="utf-8"),
        manifest,
        root / "docs" / "a.md",
    )
    assert n == 2
    assert unresolved == []
    assert "https://docs.google.com/document/d/DOC_B" in text
    assert "https://docs.google.com/spreadsheets/d/SHEET_1" in text


def test_doc_transform_names_adds_rewrite_from_manifest_link_mode(tmp_path: Path):
    manifest = _manifest(tmp_path, link_mode="rewrite_to_drive")
    item = manifest.items[0]
    assert doc_transform_names(manifest, item) == ["rewrite_links"]


def test_doc_transform_names_preserves_explicit_transforms(tmp_path: Path):
    manifest = _manifest(tmp_path, link_mode="preserve")
    item = Item(
        local="docs/x.md",
        drive_id="DOC_X",
        type="doc",
        transforms=[__import__("cowork.sync.manifest", fromlist=["Transform"]).Transform(name="strip_internal")],
    )
    assert doc_transform_names(manifest, item) == ["strip_internal"]


def test_apply_md_transforms_via_link_mode(tmp_path: Path):
    root = tmp_path
    (root / "docs").mkdir()
    (root / "docs" / "a.md").write_text("[link](b.md)\n", encoding="utf-8")
    manifest = _manifest(root)
    result = apply_md_transforms(
        root / "docs" / "a.md",
        manifest,
        doc_transform_names(manifest, manifest.items[0]),
    )
    assert result.rewrite_count == 1
    assert "DOC_B" in result.text


def test_load_manifest_link_mode(tmp_path: Path):
    (tmp_path / ".drivesync.yaml").write_text(
        yaml.dump(
            {
                "client": "demo",
                "link_mode": "rewrite_to_drive",
                "items": [
                    {"local": "a.md", "drive_id": "1", "type": "doc"},
                ],
            }
        ),
        encoding="utf-8",
    )
    manifest = load_manifest(tmp_path)
    assert manifest.link_mode == "rewrite_to_drive"
    assert manifest.effective_link_mode(manifest.items[0]) == "rewrite_to_drive"


def test_save_doc_apply_snapshot_writes_md_and_sidecar(tmp_path: Path):
    local = "docs/entregables/requisitos_v2/00_principal.md"
    applied_at = "2026-05-27T18:30:00Z"
    md_path = save_doc_apply_snapshot(
        tmp_path,
        local,
        "DRIVE123",
        "# Contenido aplicado\n",
        local_hash="sha256:abc",
        remote_modified_time="2026-05-27T18:30:05Z",
        account="test@example.com",
        applied_at=applied_at,
    )
    assert md_path == snapshot_dir(tmp_path, local) / f"{applied_at}.md"
    assert md_path.read_text(encoding="utf-8") == "# Contenido aplicado\n"
    meta = (md_path.parent / f"{applied_at}.json").read_text(encoding="utf-8")
    assert '"drive_id": "DRIVE123"' in meta
    assert '"local_hash": "sha256:abc"' in meta
    assert '"account": "test@example.com"' in meta


def test_content_mode_por_defecto_es_ast(tmp_path):
    manifest = _manifest(tmp_path)
    assert manifest.effective_content_mode(manifest.items[0]) == "ast"


def test_content_mode_del_item_gana_al_del_manifiesto(tmp_path):
    manifest = _manifest(tmp_path)
    manifest.content_mode = "docx_upload"
    assert manifest.effective_content_mode(manifest.items[0]) == "docx_upload"
    manifest.items[0].content_mode = "ast"
    assert manifest.effective_content_mode(manifest.items[0]) == "ast"


def test_load_manifest_lee_content_mode_y_doc_tab(tmp_path):
    (tmp_path / ".drivesync.yaml").write_text(
        "client: c\n"
        "content_mode: docx_upload\n"
        "items:\n"
        "  - local: docs/a.md\n"
        "    drive_id: DOC_A\n"
        "    type: doc\n"
        "    doc_tab: t.abc\n",
        encoding="utf-8",
    )
    manifest = load_manifest(tmp_path)
    assert manifest.content_mode == "docx_upload"
    assert manifest.items[0].doc_tab == "t.abc"
    assert manifest.effective_content_mode(manifest.items[0]) == "docx_upload"
