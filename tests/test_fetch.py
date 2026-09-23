"""Tests for fetch/sync assessment and text normalization."""

from pathlib import Path

from gwork.sync.fetch import assess_doc, md_to_plain_approx, normalize_plain
from gwork.sync.manifest import Item
from gwork.sync.state import DocSnapshot, file_hash


def test_assess_doc_noop():
    item = Item(local="doc.md", drive_id="abc", type="doc")
    snap = DocSnapshot(
        remote_modified_time="2026-05-27T10:00:00Z",
        applied_at="2026-05-27T10:00:00Z",
        local_hash="sha256:deadbeef",
    )
    entry = assess_doc(item, snap, Path("/nonexistent.md"), "2026-05-27T10:00:00Z")
    assert entry["sync_status"] == "missing_local"


def test_assess_doc_local_only(tmp_path: Path):
    md = tmp_path / "doc.md"
    md.write_text("# Title\n\nContent.", encoding="utf-8")
    local_h = file_hash(md)
    item = Item(local="doc.md", drive_id="abc", type="doc")
    snap = DocSnapshot(
        remote_modified_time="2026-05-27T10:00:00Z",
        applied_at="2026-05-27T10:00:00Z",
        local_hash="sha256:other",
    )
    entry = assess_doc(item, snap, md, "2026-05-27T10:00:00Z")
    assert entry["sync_status"] == "local_only"
    assert entry["local_hash"] == local_h


def test_assess_doc_remote_only(tmp_path: Path):
    md = tmp_path / "doc.md"
    md.write_text("unchanged", encoding="utf-8")
    local_h = file_hash(md)
    item = Item(local="doc.md", drive_id="abc", type="doc")
    snap = DocSnapshot(
        remote_modified_time="2026-05-27T10:00:00Z",
        applied_at="2026-05-27T10:00:00Z",
        local_hash=local_h,
    )
    entry = assess_doc(item, snap, md, "2026-05-27T12:00:00Z")
    assert entry["sync_status"] == "remote_only"
    assert entry.get("drift_reason")


def test_assess_doc_conflict(tmp_path: Path):
    md = tmp_path / "doc.md"
    md.write_text("local change", encoding="utf-8")
    item = Item(local="doc.md", drive_id="abc", type="doc")
    snap = DocSnapshot(
        remote_modified_time="2026-05-27T10:00:00Z",
        applied_at="2026-05-27T10:00:00Z",
        local_hash="sha256:other",
    )
    entry = assess_doc(item, snap, md, "2026-05-27T12:00:00Z")
    assert entry["sync_status"] == "conflict"


def test_md_to_plain_approx_strips_markdown():
    raw = "# Title\n\n**Bold** and [link](x.md)\n"
    plain = md_to_plain_approx(raw)
    assert "Title" in plain
    assert "Bold" in plain
    assert "link" in plain
    assert "**" not in plain
    assert "](" not in plain


def test_normalize_plain_collapses_blank_lines():
    assert normalize_plain("a\n\n  b\n") == "a\nb"
