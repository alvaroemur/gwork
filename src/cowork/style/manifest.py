from __future__ import annotations

"""Lectura de `.gdoc-sync.yaml`: el sistema de diseño de un Google Doc gobernado."""

from pathlib import Path
from typing import Any, Optional

import yaml

MANIFEST_NAME = ".gdoc-sync.yaml"


class StyleManifest:
    """Vista tipada del manifiesto de diseño."""

    def __init__(self, data: dict, path: Optional[Path] = None):
        self.raw = data or {}
        self.path = path
        document = self.raw.get("document", {}) or {}
        self.doc_id: str = document.get("doc_id", "")
        self.title: str = document.get("title", "")
        self.account: Optional[str] = document.get("account")
        self.template_tab_id: str = document.get("template_tab_id", "")
        self.design_system: dict = self.raw.get("design_system", {}) or {}
        self.sync_guards: dict = self.raw.get("sync_guards", {}) or {}
        self.tabs: list = self.raw.get("tabs", []) or []

    @classmethod
    def load(cls, path: Path) -> "StyleManifest":
        path = Path(path)
        if path.is_dir():
            path = path / MANIFEST_NAME
        if not path.exists():
            raise FileNotFoundError(f"No se encontró el manifiesto de estilo en {path}")
        return cls(yaml.safe_load(path.read_text(encoding="utf-8")), path=path)

    # -- secciones ---------------------------------------------------------

    @property
    def typography(self) -> dict:
        return self.design_system.get("typography", {}) or {}

    @property
    def scales(self) -> dict:
        return self.typography.get("scales", {}) or {}

    @property
    def colors(self) -> dict:
        return self.design_system.get("colors", {}) or {}

    @property
    def components(self) -> dict:
        return self.design_system.get("components", {}) or {}

    @property
    def page_layout(self) -> dict:
        return self.design_system.get("page_layout", {}) or {}

    @property
    def font_primary(self) -> str:
        return self.typography.get("font_family_primary", "Nunito")

    @property
    def font_code(self) -> str:
        return self.typography.get("font_family_code", "Courier New")

    @property
    def printable_width(self) -> float:
        return float(self.page_layout.get("printable_width", 542))

    def guard(self, name: str, default: bool = True) -> bool:
        return bool(self.sync_guards.get(name, default))

    def color(self, name: str, default: str) -> str:
        return self.colors.get(name, default)


# Mapa scale del manifiesto → namedStyleType de la Docs API.
SCALE_TO_NAMED_STYLE = {
    "title": "TITLE",
    "subtitle": "SUBTITLE",
    "heading_1": "HEADING_1",
    "heading_2": "HEADING_2",
    "heading_3": "HEADING_3",
    "heading_4": "HEADING_4",
    "heading_5": "HEADING_5",
    "heading_6": "HEADING_6",
    "normal_text": "NORMAL_TEXT",
}

NAMED_STYLE_TO_SCALE = {v: k for k, v in SCALE_TO_NAMED_STYLE.items()}
