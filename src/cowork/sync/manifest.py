from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional
import yaml


ItemType = Literal["sheet", "doc", "slides"]
SyncMode = Literal["values_patch", "replace"]
LinkMode = Literal["preserve", "rewrite_to_drive"]
ContentMode = Literal["ast", "docx_upload"]


@dataclass
class Transform:
    name: Literal["strip_internal", "rewrite_links"]
    config: dict = field(default_factory=dict)


@dataclass
class Item:
    local: str
    drive_id: str
    type: ItemType
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
    link_mode: Optional[LinkMode] = None
    content_mode: Optional[ContentMode] = None

    @property
    def state_path(self) -> Path:
        return self.root / ".drivesync.state.json"

    @property
    def preview_dir(self) -> Path:
        return self.root / ".drivesync" / "preview"

    @property
    def decisions_path(self) -> Path:
        return self.preview_dir / "decisions.yaml"

    def find_item(self, local: str) -> Optional[Item]:
        for it in self.items:
            if it.local == local:
                return it
        return None

    def effective_link_mode(self, item: Item) -> LinkMode:
        if item.link_mode:
            return item.link_mode
        if self.link_mode:
            return self.link_mode
        return "preserve"

    def effective_content_mode(self, item: Item) -> ContentMode:
        """Cómo se escribe el contenido de un Doc.

        El defecto es `ast` porque es el camino no destructivo: `docx_upload`
        reemplaza el archivo entero y hay que pedirlo explícitamente.
        """
        if item.content_mode:
            return item.content_mode
        if self.content_mode:
            return self.content_mode
        return "ast"


def load_manifest(root: Path) -> Manifest:
    path = root / ".drivesync.yaml"
    if not path.exists():
        raise FileNotFoundError(f"No se encontró .drivesync.yaml en {root}")
    data = yaml.safe_load(path.read_text())
    items = []
    for raw in data.get("items", []):
        transforms = [Transform(name=t["name"], config={k: v for k, v in t.items() if k != "name"})
                      if isinstance(t, dict) else Transform(name=t)
                      for t in raw.get("transforms", [])]
        items.append(Item(
            local=raw["local"],
            drive_id=raw["drive_id"],
            type=raw["type"],
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
    return Manifest(
        client=data["client"],
        drive_folder_id=data.get("drive_folder_id"),
        items=items,
        root=root,
        link_mode=data.get("link_mode"),
        content_mode=data.get("content_mode"),
    )
