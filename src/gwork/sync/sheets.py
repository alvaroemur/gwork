from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .gog import (
    sheets_get, sheets_metadata, sheets_update_range,
    drive_comments_list, drive_get, extract_modified_time, GogError,
)
from .manifest import Item
from .state import SheetSnapshot


# ---------------------------------------------------------------------------
# Matrix models
# ---------------------------------------------------------------------------

@dataclass
class Matrix:
    headers: list[str]
    rows: dict[str, dict[str, str]]   # row_key -> {column: value}
    row_order: list[str] = field(default_factory=list)


@dataclass
class RemoteSheet:
    matrix: Matrix
    formulas: dict[str, dict[str, str]]   # row_key -> {column: formula or ""}
    modified_time: str
    sheet_id: int
    tab_title: str


# ---------------------------------------------------------------------------
# Local reads
# ---------------------------------------------------------------------------

def read_csv_matrix(path: Path, key_column: Optional[str]) -> Matrix:
    with path.open(newline="") as f:
        all_rows = list(csv.reader(f))
    if not all_rows:
        return Matrix(headers=[], rows={}, row_order=[])
    headers = all_rows[0]
    rows: dict[str, dict[str, str]] = {}
    order: list[str] = []
    for i, raw in enumerate(all_rows[1:], start=1):
        padded = (raw + [""] * len(headers))[:len(headers)]
        row_dict = dict(zip(headers, padded))
        key = (row_dict.get(key_column) or "") if key_column else ""
        if not key:
            key = f"__idx_{i}"
        rows[key] = row_dict
        order.append(key)
    return Matrix(headers=headers, rows=rows, row_order=order)


def write_csv_matrix(path: Path, matrix: Matrix) -> None:
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(matrix.headers)
        for k in matrix.row_order:
            w.writerow([matrix.rows[k].get(h, "") for h in matrix.headers])


# ---------------------------------------------------------------------------
# Remote reads through gog
# ---------------------------------------------------------------------------

def _resolve_tab(item: Item, meta: dict) -> tuple[str, int]:
    """Return ``(tab_title, sheet_id)`` for the configured item."""
    # The Sheets API omits sheetId when it is 0 for the first tab.
    tabs = meta.get("sheets", [])
    if item.sheet_tab:
        for t in tabs:
            props = t["properties"]
            if props["title"] == item.sheet_tab:
                return props["title"], props.get("sheetId", 0)
        raise ValueError(f"Tab '{item.sheet_tab}' was not found in spreadsheet {item.drive_id}")
    props = tabs[0]["properties"]
    return props["title"], props.get("sheetId", 0)


def _rows_to_matrix(raw_values: list[list[str]], raw_formulas: list[list[str]],
                    item: Item, headers: list[str]) -> tuple[Matrix, dict[str, dict[str, str]]]:
    """Convert value and formula rows into a matrix and formula map."""
    ds = item.data_start_row - item.headers_row
    de = item.data_end_row
    width = len(headers)

    rows: dict[str, dict[str, str]] = {}
    formulas: dict[str, dict[str, str]] = {}
    order: list[str] = []

    data_rows = raw_values[ds:]
    if de is not None:
        data_rows = data_rows[:de - item.data_start_row + 1]

    formula_rows = raw_formulas[ds:] if raw_formulas else []

    for i, raw in enumerate(data_rows):
        padded = ([str(v) for v in raw] + [""] * width)[:width]
        row_dict = dict(zip(headers, padded))
        key = (row_dict.get(item.key_column) or "") if item.key_column else ""
        if not key:
            key = f"__idx_{i + 1}"
        rows[key] = row_dict
        order.append(key)

        if i < len(formula_rows):
            f_raw = formula_rows[i]
            f_pad = ([str(v) if v else "" for v in f_raw] + [""] * width)[:width]
            formulas[key] = {h: (v if v.startswith("=") else "")
                             for h, v in zip(headers, f_pad)}
        else:
            formulas[key] = {h: "" for h in headers}

    return Matrix(headers=headers, rows=rows, row_order=order), formulas


def fetch_remote_sheet(item: Item, account: Optional[str] = None) -> RemoteSheet:
    meta = sheets_metadata(item.drive_id, account)
    tab_title, sheet_id = _resolve_tab(item, meta)

    drive_meta = drive_get(item.drive_id, account)
    modified_time = extract_modified_time(drive_meta)

    # Fetch values and formulas for the complete tab.
    range_ = f"'{tab_title}'"
    raw_values = sheets_get(item.drive_id, range_, render="FORMATTED_VALUE", account=account)
    raw_formulas = sheets_get(item.drive_id, range_, render="FORMULA", account=account)

    # headers_row is one-based; raw_values is zero-based.
    hr = item.headers_row - 1
    if hr >= len(raw_values):
        return RemoteSheet(
            matrix=Matrix(headers=[], rows={}, row_order=[]),
            formulas={}, modified_time=modified_time,
            sheet_id=sheet_id, tab_title=tab_title,
        )
    headers = [str(c) for c in raw_values[hr]]

    # _rows_to_matrix receives rows starting at headers_row, inclusive.
    values_from_header = raw_values[hr:]
    formulas_from_header = raw_formulas[hr:] if raw_formulas else []
    matrix, formulas = _rows_to_matrix(values_from_header, formulas_from_header, item, headers)

    return RemoteSheet(
        matrix=matrix, formulas=formulas,
        modified_time=modified_time,
        sheet_id=sheet_id, tab_title=tab_title,
    )


def fetch_threaded_comments(drive_id: str, account: Optional[str] = None) -> list[dict]:
    try:
        comments = drive_comments_list(drive_id, account)
        return [
            {
                "author": (c.get("author") or {}).get("displayName"),
                "createdTime": c.get("createdTime"),
                "content": c.get("content"),
                "resolved": c.get("resolved", False),
            }
            for c in comments
        ]
    except GogError:
        return []


# ---------------------------------------------------------------------------
# Diff and classification
# ---------------------------------------------------------------------------

CellClass = str  # "noop" | "push" | "pull_formula" | "pending_remote" | "pending_conflict"


@dataclass
class CellDiff:
    row_key: str
    column: str
    snapshot: str
    local: str
    remote: str
    formula: str
    classification: CellClass


@dataclass
class SheetDiff:
    struct_drift: Optional[str]
    cells: list[CellDiff]
    headers: list[str]
    local_only_rows: list[str]
    remote_only_rows: list[str]


def _detect_struct_drift(snapshot: SheetSnapshot, local: Matrix, remote: Matrix) -> Optional[str]:
    issues = []
    snap_h = snapshot.headers or []
    if snap_h and snap_h != remote.headers:
        issues.append(f"remote headers: {snap_h} → {remote.headers}")
    if local.headers and local.headers != remote.headers:
        issues.append(f"local != remote: {local.headers} vs {remote.headers}")
    return "; ".join(issues) if issues else None


def diff_sheet(snapshot: SheetSnapshot, local: Matrix, remote: RemoteSheet) -> SheetDiff:
    drift = _detect_struct_drift(snapshot, local, remote.matrix)
    if drift:
        return SheetDiff(struct_drift=drift, cells=[], headers=remote.matrix.headers,
                         local_only_rows=[], remote_only_rows=[])

    snap_rows = snapshot.rows or {}
    local_rows = local.rows
    remote_rows = remote.matrix.rows
    all_keys = set(snap_rows) | set(local_rows) | set(remote_rows)
    headers = remote.matrix.headers

    cells: list[CellDiff] = []
    local_only: list[str] = []
    remote_only: list[str] = []

    for key in all_keys:
        in_snap = key in snap_rows
        in_local = key in local_rows
        in_remote = key in remote_rows

        if not in_snap and in_local and not in_remote:
            local_only.append(key)
            continue
        if not in_snap and in_remote and not in_local:
            remote_only.append(key)
            continue

        for col in headers:
            snap_v = snap_rows.get(key, {}).get(col, "")
            local_v = local_rows.get(key, {}).get(col, "")
            remote_v = remote_rows.get(key, {}).get(col, "")
            formula = remote.formulas.get(key, {}).get(col, "")

            lc = local_v != snap_v
            rc = remote_v != snap_v

            if not lc and not rc:
                cls = "noop"
            elif lc and not rc:
                cls = "push"
            elif not lc and rc:
                cls = "pull_formula" if formula else "pending_remote"
            else:
                cls = "noop" if local_v == remote_v else "pending_conflict"

            if cls != "noop":
                cells.append(CellDiff(
                    row_key=key, column=col,
                    snapshot=snap_v, local=local_v, remote=remote_v,
                    formula=formula, classification=cls,
                ))

    return SheetDiff(struct_drift=None, cells=cells, headers=headers,
                     local_only_rows=local_only, remote_only_rows=remote_only)


# ---------------------------------------------------------------------------
# A1 notation and updates through gog
# ---------------------------------------------------------------------------

def col_a1(idx: int) -> str:
    s = ""
    n = idx
    while True:
        s = chr(ord("A") + (n % 26)) + s
        n = n // 26 - 1
        if n < 0:
            break
    return s


def apply_cell_updates(drive_id: str, tab_title: str, headers: list[str],
                       remote_row_order: list[str], item: Item,
                       updates: list[tuple[str, str, str]],
                       local_rows: dict[str, dict[str, str]],
                       account: Optional[str] = None) -> None:
    """Apply ``(row_key, column, value)`` entries through ``gog sheets update``.

    Send one request per row. Changed cells use one contiguous range, while
    unchanged cells in that range retain their matching local value. This
    avoids exhausting the Sheets write quota on wide rows.
    """
    if not updates:
        return
    # Group updates so each row requires one API call.
    by_row: dict[str, dict[str, str]] = {}
    for rk, col, val in updates:
        by_row.setdefault(rk, {})[col] = val

    for rk, col_vals in by_row.items():
        if rk not in remote_row_order:
            continue
        row_idx = remote_row_order.index(rk) + item.data_start_row
        idxs = [headers.index(c) for c in col_vals if c in headers]
        if not idxs:
            continue
        lo, hi = min(idxs), max(idxs)
        local_row = local_rows.get(rk, {})
        span = []
        for ci in range(lo, hi + 1):
            col = headers[ci]
            if col in col_vals:
                span.append(col_vals[col])
            else:
                span.append(local_row.get(col, ""))
        a1 = f"'{tab_title}'!{col_a1(lo)}{row_idx}:{col_a1(hi)}{row_idx}"
        sheets_update_range(drive_id, a1, [span], account)
