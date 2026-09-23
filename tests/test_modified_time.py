"""Tests for modifiedTime extraction and Doc drift detection."""

from gwork.sync.commands import _doc_remote_drift
from gwork.sync.gog import extract_modified_time
from gwork.sync.state import DocSnapshot


def test_extract_modified_time_top_level():
    assert extract_modified_time({"modifiedTime": "2026-05-27T10:00:00Z"}) == "2026-05-27T10:00:00Z"


def test_extract_modified_time_nested_file():
    meta = {"file": {"modifiedTime": "2026-05-27T12:00:00Z", "id": "abc"}}
    assert extract_modified_time(meta) == "2026-05-27T12:00:00Z"


def test_extract_modified_time_empty():
    assert extract_modified_time({}) == ""
    assert extract_modified_time(None) == ""


def test_doc_drift_when_snapshot_remote_mt_empty():
    snap = DocSnapshot(
        remote_modified_time="",
        applied_at="2026-05-27T17:00:00Z",
        local_hash="sha256:x",
    )
    drift, reason = _doc_remote_drift("2026-05-27T18:00:00Z", snap)
    assert drift is True
    assert "after the last apply" in reason


def test_doc_drift_no_drift_if_remote_before_apply():
    snap = DocSnapshot(
        remote_modified_time="",
        applied_at="2026-05-27T18:00:00Z",
        local_hash="sha256:x",
    )
    drift, _ = _doc_remote_drift("2026-05-27T17:00:00Z", snap)
    assert drift is False


def test_doc_drift_newer_than_snapshot():
    snap = DocSnapshot(
        remote_modified_time="2026-05-26T10:00:00Z",
        applied_at="2026-05-26T11:00:00Z",
        local_hash="sha256:x",
    )
    drift, reason = _doc_remote_drift("2026-05-27T10:00:00Z", snap)
    assert drift is True
    assert "2026-05-26" in reason
