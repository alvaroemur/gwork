from __future__ import annotations

"""Discover Drive subresources and organize their local mirror safely."""

from copy import deepcopy
from pathlib import Path
import re
import unicodedata
from typing import Any, Optional

import yaml

from .gog import docs_list_tabs, drive_get, sheets_metadata
from .manifest import MANIFEST_NAME


def slugify(title: str, fallback: str = "untitled") -> str:
    normalized = unicodedata.normalize("NFKD", title)
    ascii_title = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_title).strip("-")
    return slug or fallback


def _safe_relative(value: str, label: str) -> str:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{label} must be a relative path inside the project: {value}")
    return path.as_posix()


def _value(data: dict, *keys: str) -> Any:
    for key in keys:
        if data.get(key) is not None:
            return data[key]
    return None


def _flatten_doc_tabs(tabs: list[dict], parent_id: Optional[str] = None) -> list[dict]:
    result: list[dict] = []
    for entry in tabs:
        props = entry.get("tabProperties", entry.get("properties", entry))
        tab_id = _value(props, "tabId", "id", "tab_id") or _value(entry, "tabId", "id")
        title = _value(props, "title", "name") or _value(entry, "title", "name") or str(tab_id)
        if tab_id is None:
            continue
        tab_id = str(tab_id)
        result.append({"id": tab_id, "title": str(title), "parent_id": parent_id})
        children = (
            entry.get("childTabs")
            or entry.get("children")
            or props.get("childTabs")
            or []
        )
        result.extend(_flatten_doc_tabs(children, tab_id))
    return result


def discover_drive_file(
    drive_id: str,
    item_type: str,
    account: Optional[str] = None,
) -> dict:
    meta = drive_get(drive_id, account)
    file_meta = meta.get("file", meta) if isinstance(meta, dict) else {}
    title = _value(file_meta, "name", "title") or drive_id
    if item_type == "doc":
        resources = _flatten_doc_tabs(docs_list_tabs(drive_id, account))
    elif item_type == "sheet":
        sheet_meta = sheets_metadata(drive_id, account)
        title = (
            _value(sheet_meta.get("properties", {}), "title")
            or title
        )
        resources = []
        for sheet in sheet_meta.get("sheets", []):
            props = sheet.get("properties", {})
            sheet_id = str(props.get("sheetId", 0))
            resources.append({
                "id": sheet_id,
                "title": str(props.get("title", sheet_id)),
                "parent_id": None,
            })
    else:
        raise ValueError(f"Unsupported item type: {item_type}")
    if not resources:
        raise ValueError(f"Drive file {drive_id} has no discoverable {item_type} resources")
    return {
        "drive_id": drive_id,
        "type": item_type,
        "title": str(title),
        "resources": resources,
    }


def _legacy_files(data: dict) -> list[dict]:
    grouped: dict[tuple[str, str], dict] = {}
    for item in data.get("items", []) or []:
        key = (item["drive_id"], item["type"])
        drive_file = grouped.setdefault(key, {
            "drive_id": item["drive_id"],
            "type": item["type"],
            "title": item.get("drive_title", ""),
            "directory": str(Path(item["local"]).parent),
            "resources": [],
        })
        resource_id = item.get("resource_id")
        if resource_id is None and item["type"] == "doc":
            resource_id = item.get("doc_tab")
        config = {
            k: deepcopy(v) for k, v in item.items()
            if k not in {
                "local", "drive_id", "type", "resource_id", "resource_title",
                "drive_title", "doc_tab", "sheet_tab",
            }
        }
        drive_file["resources"].append({
            "id": str(resource_id) if resource_id is not None else None,
            "title": item.get("resource_title") or item.get("sheet_tab") or "",
            "local": item["local"],
            **config,
        })
    return list(grouped.values())


def _existing_files(data: dict) -> list[dict]:
    return deepcopy(data.get("files", []) or _legacy_files(data))


def _unique_path(candidate: Path, occupied: set[str]) -> str:
    stem, suffix = candidate.stem, candidate.suffix
    parent = candidate.parent
    index = 1
    current = candidate
    while current.as_posix().casefold() in occupied:
        index += 1
        current = parent / f"{stem}-{index}{suffix}"
    value = current.as_posix()
    occupied.add(value.casefold())
    return value


def _resource_path(
    drive_file: dict,
    resource: dict,
    discovered_by_id: dict[str, dict],
    occupied: set[str],
) -> str:
    extension = ".md" if drive_file["type"] == "doc" else ".csv"
    directory = Path(drive_file["directory"])
    parent_parts: list[str] = []
    parent_id = resource.get("parent_id")
    seen: set[str] = set()
    while parent_id and parent_id not in seen:
        seen.add(parent_id)
        parent = discovered_by_id.get(parent_id)
        if not parent:
            break
        parent_parts.insert(0, slugify(parent["title"]))
        parent_id = parent.get("parent_id")
    candidate = directory.joinpath(*parent_parts, slugify(resource["title"]) + extension)
    return _unique_path(candidate, occupied)


def plan_organization(
    manifest_path: Path,
    registrations: Optional[list[tuple[str, str, Optional[str]]]] = None,
    drive_ids: Optional[list[str]] = None,
    account: Optional[str] = None,
) -> dict:
    """Return a complete manifest and a reviewable organization plan."""
    manifest_path = Path(manifest_path)
    if manifest_path.is_dir():
        manifest_path = manifest_path / MANIFEST_NAME
    data = (
        yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        if manifest_path.exists() else {}
    )
    resolved_account = account or (data.get("transport", {}) or {}).get("account")
    files = _existing_files(data)
    for drive_file in files:
        if drive_file.get("directory"):
            drive_file["directory"] = _safe_relative(
                drive_file["directory"], "directory"
            )
        for resource in drive_file.get("resources", []) or []:
            if resource.get("local"):
                resource["local"] = _safe_relative(resource["local"], "local")
    by_id = {entry["drive_id"]: entry for entry in files}

    for drive_id, item_type, directory in registrations or []:
        if drive_id in by_id:
            existing = by_id[drive_id]
            if existing["type"] != item_type:
                raise ValueError(
                    f"Drive file {drive_id} is already registered as {existing['type']}"
                )
            continue
        entry = {
            "drive_id": drive_id,
            "type": item_type,
            "title": "",
            "directory": _safe_relative(directory, "directory") if directory else "",
            "resources": [],
        }
        files.append(entry)
        by_id[drive_id] = entry

    targets = set(drive_ids or by_id)
    missing = targets - set(by_id)
    if missing:
        joined = ", ".join(sorted(missing))
        raise ValueError(
            f"Drive file(s) not registered: {joined}. "
            "Use `gwork item add --drive-id ID --type doc|sheet`."
        )

    occupied = {
        path.relative_to(manifest_path.parent).as_posix().casefold()
        for path in manifest_path.parent.rglob("*")
        if path.is_file()
    }
    for entry in files:
        occupied.update(
            resource["local"].casefold() for resource in entry.get("resources", [])
            if resource.get("local")
        )

    actions: list[dict] = []
    for drive_file in files:
        if drive_file["drive_id"] not in targets:
            continue
        discovered = discover_drive_file(
            drive_file["drive_id"], drive_file["type"], resolved_account
        )
        if not drive_file.get("directory"):
            collection = "docs" if drive_file["type"] == "doc" else "sheets"
            drive_file["directory"] = f"{collection}/{slugify(discovered['title'])}"
        if drive_file.get("title") != discovered["title"]:
            actions.append({
                "action": "update_file_title",
                "drive_id": drive_file["drive_id"],
                "from": drive_file.get("title") or None,
                "to": discovered["title"],
            })
            drive_file["title"] = discovered["title"]

        current = drive_file.get("resources", []) or []
        current_by_id = {
            str(resource["id"]): resource
            for resource in current if resource.get("id") is not None
        }
        unmatched = [resource for resource in current if resource.get("id") is None]
        discovered_by_id = {resource["id"]: resource for resource in discovered["resources"]}
        reconciled: list[dict] = []
        for remote in discovered["resources"]:
            resource = current_by_id.get(remote["id"])
            if resource is None:
                title_match = next(
                    (candidate for candidate in unmatched
                     if candidate.get("title") == remote["title"]),
                    None,
                )
                if title_match is None and len(unmatched) == 1 and len(discovered["resources"]) == 1:
                    title_match = unmatched[0]
                if (
                    title_match is None
                    and len(unmatched) == 1
                    and not unmatched[0].get("title")
                    and remote is discovered["resources"][0]
                ):
                    # A version 1 item without doc_tab/sheet_tab addressed the
                    # first resource implicitly. Preserve its local path.
                    title_match = unmatched[0]
                if title_match is not None:
                    unmatched.remove(title_match)
                    resource = title_match
                    resource["id"] = remote["id"]
                else:
                    resource = {"id": remote["id"]}
            old_title = resource.get("title")
            resource["title"] = remote["title"]
            if remote.get("parent_id"):
                resource["parent_id"] = remote["parent_id"]
            else:
                resource.pop("parent_id", None)
            resource["enabled"] = True
            resource.pop("remote_missing", None)
            if not resource.get("local"):
                resource["local"] = _resource_path(
                    drive_file, remote, discovered_by_id, occupied
                )
                actions.append({
                    "action": "create_local",
                    "drive_id": drive_file["drive_id"],
                    "resource_id": remote["id"],
                    "local": resource["local"],
                })
            elif old_title and old_title != remote["title"]:
                actions.append({
                    "action": "update_resource_title",
                    "drive_id": drive_file["drive_id"],
                    "resource_id": remote["id"],
                    "from": old_title,
                    "to": remote["title"],
                    "local": resource["local"],
                })
            reconciled.append(resource)

        discovered_ids = set(discovered_by_id)
        for resource in current:
            if resource.get("id") is not None and str(resource["id"]) in discovered_ids:
                continue
            resource["enabled"] = False
            resource["remote_missing"] = True
            reconciled.append(resource)
            actions.append({
                "action": "disable_missing_remote",
                "drive_id": drive_file["drive_id"],
                "resource_id": resource.get("id"),
                "local": resource.get("local"),
            })
        drive_file["resources"] = reconciled

    output = deepcopy(data)
    output["version"] = 2
    output.setdefault("transport", {"provider": "gog"})
    output["files"] = files
    output.pop("items", None)
    return {
        "manifest_path": manifest_path,
        "manifest": output,
        "actions": actions,
        "account": resolved_account,
    }


def apply_organization(plan: dict) -> None:
    manifest_path: Path = plan["manifest_path"]
    root = manifest_path.parent
    create_paths = [
        root / action["local"]
        for action in plan["actions"]
        if action["action"] == "create_local"
    ]
    for path in create_paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size:
            raise FileExistsError(f"Refusing to overwrite non-empty file: {path}")
    for path in create_paths:
        path.touch(exist_ok=True)
    manifest_path.write_text(
        yaml.safe_dump(plan["manifest"], sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
