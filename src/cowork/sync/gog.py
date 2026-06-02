from __future__ import annotations

"""Wrapper de subprocess para gog-cli.

Todas las llamadas usan --json --no-input para output machine-parseable.
El account se pasa como --account EMAIL cuando se especifica.
"""

import json
import subprocess
from typing import Any, Optional


class GogError(Exception):
    pass


def _run(args: list[str], account: Optional[str] = None) -> Any:
    """Ejecuta un comando gog y devuelve el JSON parseado."""
    cmd = ["gog", "--json", "--no-input"]
    if account:
        cmd += ["--account", account]
    cmd += args
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise GogError(f"gog {' '.join(args)} falló (código {result.returncode}):\n{result.stderr.strip()}")
    if not result.stdout.strip():
        return None
    return json.loads(result.stdout)


def _run_plain(args: list[str], account: Optional[str] = None) -> str:
    """Ejecuta un comando gog sin --json, devuelve stdout crudo."""
    cmd = ["gog", "--no-input"]
    if account:
        cmd += ["--account", account]
    cmd += args
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise GogError(f"gog {' '.join(args)} falló (código {result.returncode}):\n{result.stderr.strip()}")
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
    """Actualiza un rango con una matriz 2D."""
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
    """Lee modifiedTime de respuestas gog (top-level o bajo `file`)."""
    if not meta:
        return ""
    if meta.get("modifiedTime"):
        return meta["modifiedTime"]
    file_obj = meta.get("file")
    if isinstance(file_obj, dict) and file_obj.get("modifiedTime"):
        return file_obj["modifiedTime"]
    return ""


def drive_upload(local_path: str, parent: Optional[str] = None,
                 name: Optional[str] = None, account: Optional[str] = None) -> dict:
    args = ["drive", "upload", local_path]
    if parent:
        args += ["--parent", parent]
    if name:
        args += ["--name", name]
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
