from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Optional
import yaml


ItemType = Literal["sheet", "doc", "slides"]
SyncMode = Literal["values_patch", "replace"]
LinkMode = Literal["preserve", "rewrite_to_drive"]
ContentMode = Literal["ast", "docx_upload"]
TransportProvider = Literal["gog", "direct_oauth", "service_account"]

MANIFEST_NAME = ".gwork.yaml"


@dataclass
class Transport:
    provider: TransportProvider = "gog"
    account: Optional[str] = None
    credentials: Optional[str] = None


@dataclass
class Transform:
    name: Literal["strip_internal", "rewrite_links"]
    config: dict = field(default_factory=dict)


@dataclass
class Item:
    local: str
    drive_id: str
    type: ItemType
    resource_id: Optional[str] = None
    resource_title: Optional[str] = None
    drive_title: Optional[str] = None
    sheet_tab: Optional[str] = None
    headers_row: int = 1
    data_start_row: int = 2
    data_end_row: Optional[int] = None
    key_column: Optional[str] = None
    sync_mode: SyncMode = "values_patch"
    protect_styling: bool = False
    link_mode: Optional[LinkMode] = None
    content_mode: Optional[ContentMode] = None
    doc_tab: Optional[str] = None
    transforms: list[Transform] = field(default_factory=list)


@dataclass
class Manifest:
    client: str
    drive_folder_id: Optional[str]
    items: list[Item]
    root: Path
    transport: Transport = field(default_factory=Transport)
    style: dict[str, Any] = field(default_factory=dict)
    link_mode: Optional[LinkMode] = None
    content_mode: Optional[ContentMode] = None
    drive_files: list[dict[str, Any]] = field(default_factory=list)

    @property
    def state_path(self) -> Path:
        return self.root / ".gwork.state.json"

    @property
    def preview_dir(self) -> Path:
        return self.root / ".gwork" / "preview"

    @property
    def decisions_path(self) -> Path:
        return self.preview_dir / "decisions.yaml"

    def find_item(self, local: str) -> Optional[Item]:
        for it in self.items:
            if it.local == local:
                return it
        return None

    def select_items(self, selectors: Optional[list[str]] = None) -> list[Item]:
        """Resolve exact local paths, Drive IDs, or Drive/resource pairs.

        A selector must identify one item. This prevents a mistyped path from
        silently falling back to another registered item.
        """
        if not selectors:
            return list(self.items)
        selected: list[Item] = []
        for selector in selectors:
            matches = [
                item for item in self.items
                if selector in {
                    item.local,
                    item.drive_id,
                    item.resource_id,
                    (
                        f"{item.drive_id}/{item.resource_id}"
                        if item.resource_id is not None else ""
                    ),
                }
            ]
            if not matches:
                raise ValueError(
                    f"No registered item matches '{selector}'. "
                    "Run `gwork item add --drive-id ID --type doc|sheet` "
                    "to preview registration."
                )
            if len(matches) > 1:
                choices = ", ".join(
                    f"{item.local} ({item.drive_id}/{item.resource_id or '-'})"
                    for item in matches
                )
                raise ValueError(
                    f"Selector '{selector}' is ambiguous: {choices}. "
                    "Use an exact local path or DRIVE_ID/RESOURCE_ID."
                )
            if matches[0] not in selected:
                selected.append(matches[0])
        return selected

    def account_for_gog(self, override: Optional[str] = None) -> Optional[str]:
        if self.transport.provider != "gog":
            raise ValueError(
                "Sync commands currently require transport.provider: gog, "
                f"got {self.transport.provider}"
            )
        return override or self.transport.account

    def effective_link_mode(self, item: Item) -> LinkMode:
        if item.link_mode:
            return item.link_mode
        if self.link_mode:
            return self.link_mode
        return "preserve"

    def effective_content_mode(self, item: Item) -> ContentMode:
        """Return the configured Google Docs content write mode.

        AST is the safe default. ``docx_upload`` replaces the complete file and
        must be selected explicitly.
        """
        if item.content_mode:
            return item.content_mode
        if self.content_mode:
            return self.content_mode
        return "ast"


def load_manifest(root: Path) -> Manifest:
    root = Path(root)
    path = root if root.is_file() else root / MANIFEST_NAME
    if not path.exists():
        raise FileNotFoundError(f"{MANIFEST_NAME} was not found under {root}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    transport_data = data.get("transport", {}) or {}
    provider = transport_data.get("provider", "gog")
    if provider not in ("gog", "direct_oauth", "service_account"):
        raise ValueError(f"Unsupported transport provider: {provider}")
    items = []
    for raw in data.get("items", []):
        transforms = [Transform(name=t["name"], config={k: v for k, v in t.items() if k != "name"})
                      if isinstance(t, dict) else Transform(name=t)
                      for t in raw.get("transforms", [])]
        items.append(Item(
            local=raw["local"],
            drive_id=raw["drive_id"],
            type=raw["type"],
            resource_id=str(raw.get("resource_id")) if raw.get("resource_id") is not None else None,
            resource_title=raw.get("resource_title"),
            drive_title=raw.get("drive_title"),
            sheet_tab=raw.get("sheet_tab"),
            headers_row=raw.get("headers_row", 1),
            data_start_row=raw.get("data_start_row", 2),
            data_end_row=raw.get("data_end_row"),
            key_column=raw.get("key_column"),
            sync_mode=raw.get("sync_mode", "values_patch"),
            protect_styling=bool(raw.get("protect_styling", False)),
            link_mode=raw.get("link_mode"),
            content_mode=raw.get("content_mode"),
            doc_tab=raw.get("doc_tab"),
            transforms=transforms,
        ))
    drive_files = data.get("files", []) or []
    for drive_file in drive_files:
        if drive_file.get("enabled", True) is False:
            continue
        common = {
            key: value for key, value in drive_file.items()
            if key not in {"resources", "directory", "title", "enabled"}
        }
        for resource in drive_file.get("resources", []) or []:
            if resource.get("enabled", True) is False:
                continue
            raw = {**common, **resource}
            transforms = [
                Transform(
                    name=t["name"],
                    config={k: v for k, v in t.items() if k != "name"},
                ) if isinstance(t, dict) else Transform(name=t)
                for t in raw.get("transforms", [])
            ]
            item_type = drive_file["type"]
            resource_id = str(resource["id"])
            items.append(Item(
                local=resource["local"],
                drive_id=drive_file["drive_id"],
                type=item_type,
                resource_id=resource_id,
                resource_title=resource.get("title"),
                drive_title=drive_file.get("title"),
                sheet_tab=resource.get("title") if item_type == "sheet" else None,
                headers_row=raw.get("headers_row", 1),
                data_start_row=raw.get("data_start_row", 2),
                data_end_row=raw.get("data_end_row"),
                key_column=raw.get("key_column"),
                sync_mode=raw.get("sync_mode", "values_patch"),
                protect_styling=bool(raw.get("protect_styling", False)),
                link_mode=raw.get("link_mode"),
                content_mode=raw.get("content_mode"),
                doc_tab=resource_id if item_type == "doc" else None,
                transforms=transforms,
            ))
    return Manifest(
        client=data.get("client") or path.parent.name,
        drive_folder_id=data.get("drive_folder_id"),
        items=items,
        root=path.parent,
        transport=Transport(
            provider=provider,
            account=transport_data.get("account"),
            credentials=transport_data.get("credentials"),
        ),
        style=data.get("style", {}) or {},
        link_mode=data.get("link_mode"),
        content_mode=data.get("content_mode"),
        drive_files=drive_files,
    )
