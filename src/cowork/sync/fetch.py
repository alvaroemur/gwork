from __future__ import annotations

import difflib
import json
import re
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .commands import _doc_remote_drift, _plan_sheet, cmd_apply, cmd_plan
from .docs import fetch_doc_modified_time, fetch_doc_plain_text
from .gog import drive_comments_list
from .manifest import Item, Manifest, load_manifest
from .sheets import fetch_threaded_comments
from .state import DocSnapshot, State, file_hash

console = Console()


def md_to_plain_approx(md: str) -> str:
    """Aproximación legible del markdown para diff contra texto plano del Doc."""
    text = md
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    text = re.sub(r"^#+\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^>\s?", "", text, flags=re.MULTILINE)
    text = re.sub(r"^---+\s*$", "", text, flags=re.MULTILINE)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return "\n".join(lines)


def normalize_plain(text: str) -> str:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return "\n".join(lines)


def assess_doc(
    item: Item,
    snapshot: DocSnapshot,
    local_path: Path,
    remote_mt: str,
) -> dict:
    if not local_path.exists():
        return {
            "local": item.local,
            "type": "doc",
            "drive_id": item.drive_id,
            "sync_status": "missing_local",
            "remote_modified_time": remote_mt,
        }

    local_h = file_hash(local_path)
    local_changed = snapshot.local_hash != local_h
    drift, drift_reason = _doc_remote_drift(remote_mt, snapshot)

    if drift and local_changed:
        sync_status = "conflict"
    elif drift:
        sync_status = "remote_only"
    elif local_changed:
        sync_status = "local_only"
    else:
        sync_status = "noop"

    entry = {
        "local": item.local,
        "type": "doc",
        "drive_id": item.drive_id,
        "sync_status": sync_status,
        "remote_modified_time": remote_mt,
        "snapshot_remote_modified_time": snapshot.remote_modified_time or None,
        "applied_at": snapshot.applied_at,
        "local_hash": local_h,
        "snapshot_local_hash": snapshot.local_hash,
        "protect_styling": item.protect_styling,
    }
    if drift_reason:
        entry["drift_reason"] = drift_reason
    if item.protect_styling and sync_status in ("local_only", "conflict"):
        entry["protect_styling_note"] = (
            "apply vía Pandoc destruye estilo nativo; usar parches quirúrgicos o "
            "--force-content-push tras confirmación."
        )
    return entry


def _assess_sheet_item(
    manifest: Manifest,
    item: Item,
    state: State,
    account: Optional[str],
) -> dict:
    local_path = manifest.root / item.local
    if not local_path.exists():
        return {
            "local": item.local,
            "type": "sheet",
            "drive_id": item.drive_id,
            "sync_status": "missing_local",
        }
    plan = _plan_sheet(manifest, item, state, account)
    status = plan.get("status", "?")
    if status == "noop":
        sync_status = "noop"
    elif status == "doc_drift":
        sync_status = "remote_only"
    elif status == "struct_drift":
        sync_status = "conflict"
    else:
        sync_status = "local_only"
    return {
        **plan,
        "sync_status": sync_status,
        "drive_id": item.drive_id,
    }


def assess_item(
    manifest: Manifest,
    item: Item,
    state: State,
    account: Optional[str],
) -> dict:
    local_path = manifest.root / item.local
    if item.type == "doc":
        snapshot = state.get_doc(item.local)
        remote_mt = fetch_doc_modified_time(item.drive_id, account)
        return assess_doc(item, snapshot, local_path, remote_mt)
    if item.type == "sheet":
        return _assess_sheet_item(manifest, item, state, account)
    return {
        "local": item.local,
        "type": item.type,
        "sync_status": "unsupported",
        "drive_id": item.drive_id,
    }


def _format_comments(comments: list[dict]) -> list[dict]:
    rows = []
    for c in comments:
        rows.append({
            "id": c.get("id"),
            "resolved": c.get("resolved"),
            "content": (c.get("content") or "").strip(),
            "quoted": ((c.get("quotedFileContent") or {}).get("value") or "").strip()[:120],
        })
    return rows


def _unified_diff(local_text: str, remote_text: str, local_label: str, remote_label: str) -> str:
    return "".join(
        difflib.unified_diff(
            local_text.splitlines(keepends=True),
            remote_text.splitlines(keepends=True),
            fromfile=local_label,
            tofile=remote_label,
            lineterm="",
        )
    )


def cmd_fetch(
    root: Path,
    account: Optional[str] = None,
    only: Optional[list[str]] = None,
    comments: bool = False,
    diff: bool = False,
    as_json: bool = False,
) -> int:
    manifest = load_manifest(root)
    state = State(manifest.state_path)
    only_set = set(only or [])
    results = []

    for item in manifest.items:
        if only_set and item.local not in only_set:
            continue
        entry = assess_item(manifest, item, state, account)

        if comments and item.type in ("doc", "sheet"):
            raw = drive_comments_list(item.drive_id, account)
            entry["comments"] = _format_comments(raw)
            if item.type == "sheet":
                entry["comments_context"] = fetch_threaded_comments(item.drive_id, account)

        if diff and item.type == "doc":
            local_path = manifest.root / item.local
            if local_path.exists():
                local_plain = normalize_plain(md_to_plain_approx(local_path.read_text(encoding="utf-8")))
                try:
                    remote_plain = normalize_plain(
                        fetch_doc_plain_text(item.drive_id, account=account)
                    )
                    entry["diff"] = _unified_diff(
                        local_plain,
                        remote_plain,
                        f"local:{item.local}",
                        f"drive:{item.drive_id}",
                    )
                except Exception as exc:
                    entry["diff_error"] = str(exc)

        results.append(entry)

    if as_json:
        console.print_json(json.dumps(results, ensure_ascii=False, indent=2))
        return 0

    table = Table(title=f"fetch · {manifest.client}", show_lines=False)
    table.add_column("item")
    table.add_column("tipo")
    table.add_column("estado")
    table.add_column("remoto")
    for entry in results:
        status = entry.get("sync_status", entry.get("status", "?"))
        color = {
            "noop": "dim",
            "local_only": "green",
            "remote_only": "yellow",
            "conflict": "red",
            "missing_local": "red",
        }.get(status, "white")
        remote_mt = (entry.get("remote_modified_time") or "")[:19]
        table.add_row(
            entry["local"],
            entry.get("type", "?"),
            f"[{color}]{status}[/{color}]",
            remote_mt,
        )
    console.print(table)

    for entry in results:
        if entry.get("drift_reason"):
            console.print(f"[yellow]{entry['local']}:[/yellow] {entry['drift_reason']}")
        if entry.get("protect_styling_note"):
            console.print(f"[yellow]{entry['local']}:[/yellow] {entry['protect_styling_note']}")

        if comments and entry.get("comments"):
            open_comments = [c for c in entry["comments"] if not c.get("resolved")]
            if open_comments:
                console.print(Panel(
                    "\n".join(
                        f"· {c['content'][:200]}"
                        + (f"\n  ↳ «{c['quoted']}»" if c.get("quoted") else "")
                        for c in open_comments[:8]
                    ),
                    title=f"Comentarios abiertos · {entry['local']}",
                ))

        if diff and entry.get("diff"):
            snippet = entry["diff"]
            if len(snippet) > 4000:
                snippet = snippet[:4000] + "\n… (diff truncado)\n"
            console.print(Panel(snippet, title=f"diff · {entry['local']}", border_style="cyan"))

    blockers = [e for e in results if e.get("sync_status") in ("remote_only", "conflict")]
    if blockers:
        console.print(
            f"\n[yellow]{len(blockers)} item(s) con cambios solo en Drive o conflicto — "
            f"revisá antes de sync.[/yellow]"
        )
    return 0


def cmd_sync(
    root: Path,
    account: Optional[str] = None,
    only: Optional[list[str]] = None,
    apply: bool = False,
    force_content_push: bool = False,
    comments: bool = False,
    diff: bool = False,
) -> int:
    """Preflight fetch → plan → (opcional) apply. No escribe si hay drift remoto."""
    manifest = load_manifest(root)
    state = State(manifest.state_path)
    only_set = set(only or [])

    console.print("[bold]sync · preflight fetch[/bold]")
    blockers = []
    for item in manifest.items:
        if only_set and item.local not in only_set:
            continue
        entry = assess_item(manifest, item, state, account)
        status = entry.get("sync_status")
        console.print(f"  {item.local}: [{status}]")
        if status in ("remote_only", "conflict"):
            blockers.append(entry)
            if entry.get("drift_reason"):
                console.print(f"    [yellow]{entry['drift_reason']}[/yellow]")

    if blockers:
        console.print(
            "\n[red]Sync abortado:[/red] hay cambios en Drive que no vienen del markdown local. "
            "Corré `cowork sync fetch --comments --diff` y resolvé en la UI o alineá el local "
            "antes de empujar."
        )
        return 2

    if comments or diff:
        cmd_fetch(root, account=account, only=only, comments=comments, diff=diff)
        console.print()

    console.print("[bold]sync · plan[/bold]")
    plan_rc = cmd_plan(root, account=account)
    if plan_rc != 0:
        return plan_rc

    if not apply:
        console.print(
            "\n[dim]Preflight OK. Para empujar: `cowork sync sync --apply` "
            "(+ `--force-content-push` si hay docs con protect_styling).[/dim]"
        )
        return 0

    console.print("[bold]sync · apply[/bold]")
    return cmd_apply(
        root,
        only=only or [],
        account=account,
        force_content_push=force_content_push,
    )
