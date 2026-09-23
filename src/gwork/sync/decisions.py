from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import yaml


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_decisions(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=120))


def read_decisions(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def has_pending(doc: dict) -> list[str]:
    """Return descriptions of items with unresolved decisions."""
    pending = []
    for it in doc.get("items", []):
        for p in it.get("pending", []):
            if p.get("decision", "pending") == "pending":
                pending.append(f"{it['local']} {p['row_key']}/{p['column']}")
        if it.get("struct_drift") and it.get("drift_decision", "pending") == "pending":
            pending.append(f"{it['local']} struct_drift")
        if it.get("drift_reason") and it.get("drift_decision", "pending") == "pending":
            pending.append(f"{it['local']} doc_drift")
    return pending
