from __future__ import annotations

import json
from pathlib import Path
from typing import Optional


def snapshot_dir(manifest_root: Path, local: str) -> Path:
    """Return the snapshot directory for a local item using a sanitized path."""
    sanitized = local.replace("/", "__")
    return manifest_root / ".gwork" / "snapshots" / sanitized


def save_doc_apply_snapshot(
    manifest_root: Path,
    local: str,
    drive_id: str,
    content: str,
    *,
    local_hash: str,
    remote_modified_time: Optional[str],
    account: Optional[str],
    applied_at: str,
) -> Path:
    """Save applied Markdown and JSON metadata after a successful apply."""
    out_dir = snapshot_dir(manifest_root, local)
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / f"{applied_at}.md"
    meta_path = out_dir / f"{applied_at}.json"
    md_path.write_text(content, encoding="utf-8")
    meta_path.write_text(
        json.dumps(
            {
                "local": local,
                "drive_id": drive_id,
                "applied_at": applied_at,
                "local_hash": local_hash,
                "remote_modified_time": remote_modified_time,
                "account": account,
            },
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return md_path
