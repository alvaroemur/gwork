from __future__ import annotations

"""Subprocess wrapper for gog-cli.

All calls use --json --no-input for machine-readable output.
When specified, the account is passed as --account EMAIL.
"""

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Optional


class GogError(Exception):
    pass


def _run(args: list[str], account: Optional[str] = None) -> Any:
    """Run a gog command and return parsed JSON."""
    cmd = ["gog", "--json", "--no-input"]
    if account:
        cmd += ["--account", account]
    cmd += args
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise GogError(f"gog {' '.join(args)} failed (code {result.returncode}):\n{result.stderr.strip()}")
    if not result.stdout.strip():
        return None
    return json.loads(result.stdout)


def _run_plain(args: list[str], account: Optional[str] = None) -> str:
    """Run a gog command without --json and return raw stdout."""
    cmd = ["gog", "--no-input"]
    if account:
        cmd += ["--account", account]
    cmd += args
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise GogError(f"gog {' '.join(args)} failed (code {result.returncode}):\n{result.stderr.strip()}")
    return result.stdout


# ---------------------------------------------------------------------------
# Sheets
# ---------------------------------------------------------------------------

def sheets_metadata(spreadsheet_id: str, account: Optional[str] = None) -> dict:
    return _run(["sheets", "metadata", spreadsheet_id], account)


def sheets_get(spreadsheet_id: str, range_: str, render: str = "FORMATTED_VALUE",
               account: Optional[str] = None) -> list[list[str]]:
    data = _run(["sheets", "get", spreadsheet_id, range_, "--render", render], account)
    return data.get("values", []) if data else []


def sheets_update_cell(spreadsheet_id: str, a1: str, value: str,
                       account: Optional[str] = None) -> None:
    _run(["sheets", "update", spreadsheet_id, a1,
          "--values-json", json.dumps([[value]])], account)


def sheets_update_range(spreadsheet_id: str, a1: str, values: list[list[str]],
                        account: Optional[str] = None) -> None:
    """Update a range with a 2D matrix."""
    _run(["sheets", "update", spreadsheet_id, a1,
          "--values-json", json.dumps(values)], account)


def sheets_format(spreadsheet_id: str, range_: str, format_json: dict,
                  fields: Optional[str] = None, account: Optional[str] = None) -> None:
    args = ["sheets", "format", spreadsheet_id, range_,
            "--format-json", json.dumps(format_json)]
    if fields:
        args += ["--format-fields", fields]
    _run(args, account)


# ---------------------------------------------------------------------------
# Drive
# ---------------------------------------------------------------------------

def drive_get(file_id: str, account: Optional[str] = None) -> dict:
    return _run(["drive", "get", file_id], account)


def extract_modified_time(meta: Optional[dict]) -> str:
    """Read modifiedTime from top-level or nested `file` gog responses."""
    if not meta:
        return ""
    if meta.get("modifiedTime"):
        return meta["modifiedTime"]
    file_obj = meta.get("file")
    if isinstance(file_obj, dict) and file_obj.get("modifiedTime"):
        return file_obj["modifiedTime"]
    return ""


def drive_upload(local_path: str, parent: Optional[str] = None,
                 name: Optional[str] = None, account: Optional[str] = None,
                 convert: bool = False) -> dict:
    args = ["drive", "upload", local_path]
    if parent:
        args += ["--parent", parent]
    if name:
        args += ["--name", name]
    if convert:
        args.append("--convert")
    return _run(args, account)


def drive_comments_list(file_id: str, account: Optional[str] = None) -> list[dict]:
    data = _run(["drive", "comments", "list", file_id], account)
    if isinstance(data, list):
        return data
    return data.get("comments", []) if data else []


# ---------------------------------------------------------------------------
# Docs
# ---------------------------------------------------------------------------

def docs_info(doc_id: str, account: Optional[str] = None) -> dict:
    return _run(["docs", "info", doc_id], account)


def docs_create(title: str, parent: Optional[str] = None,
                account: Optional[str] = None) -> dict:
    args = ["docs", "create", title]
    if parent:
        args += ["--parent", parent]
    return _run(args, account)


def docs_copy(doc_id: str, title: str, parent: Optional[str] = None,
              account: Optional[str] = None) -> dict:
    args = ["docs", "copy", doc_id, title]
    if parent:
        args += ["--parent", parent]
    return _run(args, account)


def docs_raw(doc_id: str, tab_id: Optional[str] = None,
             all_tabs: bool = False, account: Optional[str] = None) -> dict:
    """Return raw Documents.Get output. tab_id makes indexes tab-local."""
    args = ["docs", "raw", doc_id]
    if tab_id:
        args.append(f"--tab={tab_id}")
    elif all_tabs:
        args.append("--all-tabs")
    return _run(args, account)


def docs_list_tabs(doc_id: str, account: Optional[str] = None) -> list:
    data = _run(["docs", "list-tabs", doc_id], account)
    if isinstance(data, list):
        return data
    return data.get("tabs", []) if data else []


def docs_add_tab(doc_id: str, title: str,
                 account: Optional[str] = None) -> dict:
    return _run(["docs", "add-tab", doc_id, f"--title={title}"], account)


def docs_write_markdown(doc_id: str, tab: str, markdown_path: Path,
                        account: Optional[str] = None) -> dict:
    return _run(
        [
            "docs", "write", doc_id,
            f"--tab={tab}",
            f"--file={markdown_path}",
            "--markdown",
            "--replace",
        ],
        account,
    )


def docs_delete_range(doc_id: str, tab_id: Optional[str], start: int, end: int,
                      account: Optional[str] = None) -> None:
    args = ["docs", "delete", doc_id, f"--start={start}", f"--end={end}"]
    if tab_id:
        args.append(f"--tab={tab_id}")
    _run(args, account)


def docs_page_layout(doc_id: str, tab_id: Optional[str] = None,
                     size: str = "Letter", margins: Optional[dict] = None,
                     account: Optional[str] = None) -> None:
    args = ["docs", "page-layout", doc_id, "--layout=pages", f"--page-size={size}"]
    if tab_id:
        args.append(f"--tab={tab_id}")
    for edge in ("top", "bottom", "left", "right"):
        if margins and edge in margins:
            args.append(f"--margin-{edge}={margins[edge]}")
    _run(args, account)


def docs_pin_table_header(doc_id: str, tab_id: Optional[str], table_index: int = 1,
                          rows: int = 1, account: Optional[str] = None) -> None:
    args = ["docs", "table-row", "pin-header", doc_id,
            f"--table={table_index}", f"--rows={rows}"]
    if tab_id:
        args.append(f"--tab={tab_id}")
    _run(args, account)


# ---------------------------------------------------------------------------
# Persisted batch (Docs API batchUpdate with raw requests)
# ---------------------------------------------------------------------------

def batch_dir() -> Path:
    """Return the directory for persisted gog batches."""
    candidates = []
    gog_home = os.environ.get("GOG_HOME")
    if gog_home:
        candidates.append(Path(gog_home) / "batches")
    candidates += [
        Path.home() / "Library" / "Application Support" / "gogcli" / "batches",
        Path.home() / ".config" / "gogcli" / "batches",
    ]
    for c in candidates:
        if c.is_dir():
            return c
    return candidates[-1]


def batch_execute(doc_id: str, requests: list, account: Optional[str] = None,
                  source: str = "gwork.style") -> dict:
    """Submit raw Docs API requests in one batchUpdate.

    gog lacks flags for the full API surface, including borderBottom and
    updateTableColumnProperties. `gog batch` persists the batch as JSON,
    which this function extends with literal requests before submission.
    """
    if not requests:
        return {"requests": 0, "status": "empty"}

    begin = _run(["batch", "begin", f"--doc={doc_id}"], account)
    batch_id = begin["batch_id"]
    batch_file = batch_dir() / f"{batch_id}.json"
    try:
        data = json.loads(batch_file.read_text(encoding="utf-8"))
        data.setdefault("requests", [])
        for req in requests:
            data["requests"].append({"command": source, "request": req})
        batch_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return _run(["batch", "end", "--auto-split", batch_id], account)
    except Exception:
        try:
            _run(["batch", "abort", batch_id], account)
        except GogError:
            pass
        raise
