from __future__ import annotations

"""Read the unified ``.gwork.yaml`` manifest."""

from pathlib import Path
from typing import Any, Optional

import yaml

from ..sync.manifest import MANIFEST_NAME


class StyleManifest:
    """Typed view over the manifest's ``style`` section."""

    def __init__(self, data: dict, path: Optional[Path] = None):
        self.raw = data or {}
        self.path = path
        legacy_document = self.raw.get("document", {}) or {}
        legacy_tokens = self.raw.get("design_system", {}) or {}
        self.style: dict = self.raw.get("style", {}) or {}
        if not self.style and legacy_tokens:
            self.style = {
                "document_id": legacy_document.get("doc_id", ""),
                "title": legacy_document.get("title", ""),
                "template_tab_id": legacy_document.get("template_tab_id", ""),
                "tokens": legacy_tokens,
                "sync_guards": self.raw.get("sync_guards", {}) or {},
                "tabs": self.raw.get("tabs", []) or [],
            }
        transport = self.raw.get("transport", {}) or {}
        items = self.raw.get("items", []) or []
        first_doc = next((item for item in items if item.get("type") == "doc"), {})

        self.doc_id: str = (
            self.style.get("document_id")
            or self.style.get("doc_id")
            or first_doc.get("drive_id", "")
        )
        self.title: str = self.style.get("title", "")
        self.account: Optional[str] = transport.get("account") or legacy_document.get("account")
        self.provider: str = transport.get("provider", "gog")
        self.template_tab: str = self.style.get("template_tab", "_template")
        self.template_tab_id: str = self.style.get("template_tab_id", "")
        self.design_system: dict = self.style.get("tokens", {}) or {}
        self.sync_guards: dict = self.style.get("sync_guards", {}) or {}
        self.tabs: list = self.style.get("tabs", []) or []

    @classmethod
    def load(cls, path: Path) -> "StyleManifest":
        path = Path(path)
        if path.is_dir():
            path = path / MANIFEST_NAME
        if not path.exists():
            raise FileNotFoundError(f"Style manifest was not found at {path}")
        manifest = cls(yaml.safe_load(path.read_text(encoding="utf-8")) or {}, path=path)
        if manifest.provider != "gog":
            raise ValueError(
                f"Style operations currently require transport.provider: gog, got {manifest.provider}"
            )
        return manifest

    def write_tokens(self, tokens: dict[str, Any], template_tab_id: str = "") -> None:
        """Persist extracted tokens without replacing unrelated manifest data."""
        if self.path is None:
            raise ValueError("Cannot update a manifest without a path")
        data = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        style = data.setdefault("style", {})
        style["template_tab"] = self.template_tab
        style["tokens"] = tokens
        if template_tab_id:
            style["template_tab_id"] = template_tab_id
        self.path.write_text(
            yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        self.raw = data
        self.style = style
        self.design_system = tokens
        if template_tab_id:
            self.template_tab_id = template_tab_id

    @property
    def typography(self) -> dict:
        return self.design_system.get("typography", {}) or {}

    @property
    def scales(self) -> dict:
        nested = self.typography.get("scales")
        if nested:
            return nested
        return {
            key: value
            for key, value in self.typography.items()
            if key in SCALE_TO_NAMED_STYLE and isinstance(value, dict)
        }

    @property
    def colors(self) -> dict:
        return self.design_system.get("colors", {}) or {}

    @property
    def components(self) -> dict:
        components = dict(self.design_system.get("components", {}) or {})
        if "callout" in components and "callouts" not in components:
            components["callouts"] = components["callout"]
        return components

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


# Manifest scale to Google Docs namedStyleType.
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
