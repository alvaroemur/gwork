from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


@dataclass
class SheetSnapshot:
    headers: list[str] = field(default_factory=list)
    rows: dict[str, dict[str, str]] = field(default_factory=dict)  # row_key -> {column: value}
    remote_modified_time: Optional[str] = None
    applied_at: Optional[str] = None
    values_hash: Optional[str] = None


@dataclass
class DocSnapshot:
    remote_modified_time: Optional[str] = None
    local_hash: Optional[str] = None
    applied_at: Optional[str] = None


class State:
    def __init__(self, path: Path):
        self.path = path
        self.data: dict = {"items": {}}
        if path.exists():
            self.data = json.loads(path.read_text())

    def get_sheet(self, local: str) -> SheetSnapshot:
        raw = self.data["items"].get(local)
        if not raw or raw.get("type") != "sheet":
            return SheetSnapshot()
        return SheetSnapshot(
            headers=raw.get("headers", []),
            rows=raw.get("rows", {}),
            remote_modified_time=raw.get("remote_modified_time"),
            applied_at=raw.get("applied_at"),
            values_hash=raw.get("values_hash"),
        )

    def get_doc(self, local: str) -> DocSnapshot:
        raw = self.data["items"].get(local)
        if not raw or raw.get("type") != "doc":
            return DocSnapshot()
        return DocSnapshot(
            remote_modified_time=raw.get("remote_modified_time"),
            local_hash=raw.get("local_hash"),
            applied_at=raw.get("applied_at"),
        )

    def set_sheet(self, local: str, snap: SheetSnapshot):
        d = asdict(snap)
        d["type"] = "sheet"
        d["applied_at"] = d.get("applied_at") or _now_iso()
        self.data["items"][local] = d

    def set_doc(self, local: str, snap: DocSnapshot):
        d = asdict(snap)
        d["type"] = "doc"
        d["applied_at"] = d.get("applied_at") or _now_iso()
        self.data["items"][local] = d

    def save(self):
        self.path.write_text(json.dumps(self.data, indent=2, ensure_ascii=False, sort_keys=True))


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return f"sha256:{h.hexdigest()}"


def matrix_hash(headers: list[str], rows: dict[str, dict[str, str]]) -> str:
    h = hashlib.sha256()
    h.update(json.dumps(headers, ensure_ascii=False).encode())
    for k in sorted(rows.keys()):
        h.update(k.encode())
        h.update(json.dumps(rows[k], sort_keys=True, ensure_ascii=False).encode())
    return f"sha256:{h.hexdigest()}"
