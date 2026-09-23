from pathlib import Path

import pytest
import yaml

from gwork.sync.manifest import load_manifest
from gwork.sync.organization import (
    apply_organization,
    discover_drive_file,
    plan_organization,
    slugify,
)
from gwork.style.manifest import StyleManifest


def _write_manifest(root: Path, data: dict) -> Path:
    path = root / ".gwork.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def test_slugify_is_deterministic():
    assert slugify("  Résumé / Q3  ") == "resume-q3"
    assert slugify("///") == "untitled"


def test_registration_rejects_paths_outside_project(tmp_path):
    path = _write_manifest(tmp_path, {"version": 1, "items": []})

    with pytest.raises(ValueError, match="relative path inside the project"):
        plan_organization(
            path,
            registrations=[("DOC", "doc", "../../outside")],
            drive_ids=["DOC"],
        )


def test_discover_doc_flattens_nested_tabs(monkeypatch):
    monkeypatch.setattr(
        "gwork.sync.organization.drive_get",
        lambda *_: {"file": {"name": "Project brief"}},
    )
    monkeypatch.setattr(
        "gwork.sync.organization.docs_list_tabs",
        lambda *_: [
            {
                "tabProperties": {"tabId": "parent", "title": "Overview"},
                "childTabs": [
                    {"tabProperties": {"tabId": "child", "title": "Details"}}
                ],
            }
        ],
    )

    discovered = discover_drive_file("DOC", "doc")

    assert discovered["title"] == "Project brief"
    assert discovered["resources"] == [
        {"id": "parent", "title": "Overview", "parent_id": None},
        {"id": "child", "title": "Details", "parent_id": "parent"},
    ]


def test_discover_sheet_uses_stable_sheet_ids(monkeypatch):
    monkeypatch.setattr(
        "gwork.sync.organization.drive_get",
        lambda *_: {"name": "Fallback"},
    )
    monkeypatch.setattr(
        "gwork.sync.organization.sheets_metadata",
        lambda *_: {
            "properties": {"title": "Pipeline"},
            "sheets": [
                {"properties": {"sheetId": 0, "title": "Current"}},
                {"properties": {"sheetId": 42, "title": "Archive"}},
            ],
        },
    )

    discovered = discover_drive_file("SHEET", "sheet")

    assert discovered["title"] == "Pipeline"
    assert [resource["id"] for resource in discovered["resources"]] == ["0", "42"]


def test_plan_creates_nested_paths_and_handles_collisions(tmp_path, monkeypatch):
    path = _write_manifest(tmp_path, {
        "version": 1,
        "transport": {"provider": "gog", "account": "user@example.com"},
        "style": {"tokens": {"font": "Inter"}},
        "items": [],
    })
    occupied = tmp_path / "docs" / "project-brief" / "Overview.md"
    occupied.parent.mkdir(parents=True)
    occupied.write_text("user content", encoding="utf-8")
    monkeypatch.setattr(
        "gwork.sync.organization.discover_drive_file",
        lambda *_: {
            "drive_id": "DOC",
            "type": "doc",
            "title": "Project brief",
            "resources": [
                {"id": "a", "title": "Overview", "parent_id": None},
                {"id": "b", "title": "Details", "parent_id": "a"},
            ],
        },
    )

    plan = plan_organization(
        path,
        registrations=[("DOC", "doc", None)],
        drive_ids=["DOC"],
    )
    resources = plan["manifest"]["files"][0]["resources"]

    assert resources[0]["local"] == "docs/project-brief/overview-2.md"
    assert resources[1]["local"] == "docs/project-brief/overview/details.md"
    assert plan["manifest"]["style"] == {"tokens": {"font": "Inter"}}
    assert occupied.read_text(encoding="utf-8") == "user content"


def test_renamed_resource_keeps_local_path_and_updates_title(tmp_path, monkeypatch):
    path = _write_manifest(tmp_path, {
        "version": 2,
        "files": [{
            "drive_id": "SHEET",
            "type": "sheet",
            "title": "Metrics",
            "directory": "sheets/metrics",
            "resources": [{
                "id": "7",
                "title": "Old title",
                "local": "sheets/metrics/old-title.csv",
                "key_column": "id",
            }],
        }],
    })
    monkeypatch.setattr(
        "gwork.sync.organization.discover_drive_file",
        lambda *_: {
            "drive_id": "SHEET",
            "type": "sheet",
            "title": "Metrics",
            "resources": [{"id": "7", "title": "New title", "parent_id": None}],
        },
    )

    plan = plan_organization(path)
    resource = plan["manifest"]["files"][0]["resources"][0]

    assert resource["title"] == "New title"
    assert resource["local"] == "sheets/metrics/old-title.csv"
    assert resource["key_column"] == "id"
    assert any(action["action"] == "update_resource_title" for action in plan["actions"])


def test_apply_preserves_nonempty_files_and_disables_removed_resources(
    tmp_path, monkeypatch
):
    local = tmp_path / "docs" / "brief" / "kept.md"
    local.parent.mkdir(parents=True)
    local.write_text("keep me", encoding="utf-8")
    path = _write_manifest(tmp_path, {
        "version": 2,
        "files": [{
            "drive_id": "DOC",
            "type": "doc",
            "title": "Brief",
            "directory": "docs/brief",
            "resources": [{
                "id": "gone",
                "title": "Gone",
                "local": "docs/brief/kept.md",
            }],
        }],
    })
    monkeypatch.setattr(
        "gwork.sync.organization.discover_drive_file",
        lambda *_: {
            "drive_id": "DOC",
            "type": "doc",
            "title": "Brief",
            "resources": [{"id": "new", "title": "New", "parent_id": None}],
        },
    )

    plan = plan_organization(path)
    apply_organization(plan)
    written = yaml.safe_load(path.read_text(encoding="utf-8"))

    assert local.read_text(encoding="utf-8") == "keep me"
    assert written["files"][0]["resources"][1]["remote_missing"] is True
    assert written["files"][0]["resources"][1]["enabled"] is False
    assert (tmp_path / "docs" / "brief" / "new.md").exists()


def test_legacy_items_migrate_without_losing_item_options(tmp_path, monkeypatch):
    path = _write_manifest(tmp_path, {
        "version": 1,
        "transport": {"provider": "gog"},
        "items": [{
            "local": "data/current.csv",
            "drive_id": "SHEET",
            "type": "sheet",
            "sheet_tab": "Current",
            "key_column": "record_id",
            "protect_styling": True,
        }],
    })
    monkeypatch.setattr(
        "gwork.sync.organization.discover_drive_file",
        lambda *_: {
            "drive_id": "SHEET",
            "type": "sheet",
            "title": "Data",
            "resources": [{"id": "0", "title": "Current", "parent_id": None}],
        },
    )

    plan = plan_organization(path)
    apply_organization(plan)
    manifest = load_manifest(tmp_path)

    assert "items" not in plan["manifest"]
    assert manifest.items[0].resource_id == "0"
    assert manifest.items[0].key_column == "record_id"
    assert manifest.items[0].protect_styling is True


def test_legacy_item_without_subresource_maps_to_first_remote_resource(
    tmp_path, monkeypatch
):
    path = _write_manifest(tmp_path, {
        "version": 1,
        "items": [{
            "local": "docs/brief.md",
            "drive_id": "DOC",
            "type": "doc",
        }],
    })
    monkeypatch.setattr(
        "gwork.sync.organization.discover_drive_file",
        lambda *_: {
            "drive_id": "DOC",
            "type": "doc",
            "title": "Brief",
            "resources": [
                {"id": "root", "title": "Main", "parent_id": None},
                {"id": "other", "title": "Notes", "parent_id": None},
            ],
        },
    )

    plan = plan_organization(path)
    resources = plan["manifest"]["files"][0]["resources"]

    assert resources[0]["id"] == "root"
    assert resources[0]["local"] == "docs/brief.md"
    assert resources[1]["id"] == "other"


def test_selection_fails_on_no_match_and_ambiguous_drive_id(tmp_path):
    _write_manifest(tmp_path, {
        "version": 2,
        "files": [{
            "drive_id": "DOC",
            "type": "doc",
            "title": "Brief",
            "directory": "docs/brief",
            "resources": [
                {"id": "a", "title": "A", "local": "docs/brief/a.md"},
                {"id": "b", "title": "B", "local": "docs/brief/b.md"},
            ],
        }],
    })
    manifest = load_manifest(tmp_path)

    with pytest.raises(ValueError, match="No registered item"):
        manifest.select_items(["docs/brief/missing.md"])
    with pytest.raises(ValueError, match="ambiguous"):
        manifest.select_items(["DOC"])
    assert manifest.select_items(["DOC/b"])[0].local == "docs/brief/b.md"


def test_style_manifest_can_infer_doc_from_version_two_files():
    manifest = StyleManifest({
        "version": 2,
        "files": [{
            "drive_id": "DOC",
            "type": "doc",
            "resources": [],
        }],
    })

    assert manifest.doc_id == "DOC"
