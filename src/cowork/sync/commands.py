from __future__ import annotations

from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.table import Table

from .decisions import has_pending, now_iso, read_decisions, write_decisions
from .docs import fetch_doc_modified_time, md_to_docx, update_doc_content
from .manifest import Item, Manifest, load_manifest
from . import sheets as sh
from .state import DocSnapshot, SheetSnapshot, State, file_hash, matrix_hash
from .transforms import apply_md_transforms


console = Console()


# =====================================================================
#  PLAN
# =====================================================================

def cmd_bootstrap(root: Path, source: str = "remote", account: Optional[str] = None) -> int:
    """Establece el snapshot inicial para todos los items sin snapshot previo.

    source='remote' — toma el estado actual de Drive como verdad.
    source='local'  — toma los CSVs locales como verdad (no toca Drive).
    """
    manifest = load_manifest(root)
    state = State(manifest.state_path)

    console.print(f"[bold]bootstrap · {manifest.client}[/bold] — fuente: [cyan]{source}[/cyan]")

    for item in manifest.items:
        local_path = manifest.root / item.local
        if not local_path.exists():
            console.print(f"[red]skip {item.local} (no existe localmente)[/red]"); continue

        if item.type == "sheet":
            existing = state.get_sheet(item.local)
            if existing.headers:
                console.print(f"[dim]skip {item.local} (ya tiene snapshot)[/dim]"); continue

            if source == "remote":
                remote = sh.fetch_remote_sheet(item, account)
                state.set_sheet(item.local, SheetSnapshot(
                    headers=remote.matrix.headers,
                    rows=remote.matrix.rows,
                    remote_modified_time=remote.modified_time,
                    applied_at=now_iso(),
                    values_hash=matrix_hash(remote.matrix.headers, remote.matrix.rows),
                ))
            else:  # local
                local_matrix = sh.read_csv_matrix(local_path, item.key_column)
                from .gog import drive_get
                drive_meta = drive_get(item.drive_id, account)
                state.set_sheet(item.local, SheetSnapshot(
                    headers=local_matrix.headers,
                    rows=local_matrix.rows,
                    remote_modified_time=drive_meta.get("modifiedTime", ""),
                    applied_at=now_iso(),
                    values_hash=matrix_hash(local_matrix.headers, local_matrix.rows),
                ))
            console.print(f"[green]✓[/green] {item.local}")

        elif item.type == "doc":
            existing = state.get_doc(item.local)
            if existing.local_hash:
                console.print(f"[dim]skip {item.local} (ya tiene snapshot)[/dim]"); continue
            remote_mt = fetch_doc_modified_time(item.drive_id, account)
            state.set_doc(item.local, DocSnapshot(
                remote_modified_time=remote_mt,
                local_hash=file_hash(local_path),
                applied_at=now_iso(),
            ))
            console.print(f"[green]✓[/green] {item.local}")

    state.save()
    console.print(f"\n[bold green]bootstrap completado[/bold green] — corré `cowork sync plan` ahora.")
    return 0


def cmd_plan(root: Path, account: Optional[str] = None) -> int:
    manifest = load_manifest(root)
    state = State(manifest.state_path)
    manifest.preview_dir.mkdir(parents=True, exist_ok=True)

    decisions = {
        "generated_at": now_iso(),
        "client": manifest.client,
        "account": account,
        "items": [],
    }

    table = Table(title=f"plan · {manifest.client}", show_lines=False)
    table.add_column("item"); table.add_column("tipo"); table.add_column("estado")

    for item in manifest.items:
        local_path = manifest.root / item.local
        if not local_path.exists():
            entry = {"local": item.local, "type": item.type, "status": "missing_local"}
        elif item.type == "sheet":
            entry = _plan_sheet(manifest, item, state, account)
        elif item.type == "doc":
            entry = _plan_doc(manifest, item, state, account)
        else:
            entry = {"local": item.local, "type": item.type, "status": "unsupported"}

        decisions["items"].append(entry)
        table.add_row(item.local, item.type, _status_label(entry))

    write_decisions(manifest.decisions_path, decisions)
    console.print(table)
    console.print(f"\n[dim]decisions.yaml → {manifest.decisions_path}[/dim]")
    pending = has_pending(decisions)
    if pending:
        console.print(f"[yellow]{len(pending)} pendientes sin resolver.[/yellow]")
    else:
        console.print("[green]Todo listo para apply.[/green]")
    return 0


def _status_label(entry: dict) -> str:
    s = entry.get("status", "?")
    if s == "noop":           return "[dim]sin cambios[/dim]"
    if s == "struct_drift":   return f"[red]struct drift:[/red] {entry.get('struct_drift','')}"
    if s == "doc_drift":      return f"[red]doc drift:[/red] {entry.get('drift_reason','')}"
    if s == "missing_local":  return "[red]archivo local no existe[/red]"
    if s == "ok":
        bits = []
        auto = entry.get("auto_merge", [])
        pend = entry.get("pending", [])
        ts   = entry.get("transforms_summary")
        if auto: bits.append(f"{len(auto)} auto")
        if pend: bits.append(f"[yellow]{len(pend)} pendientes[/yellow]")
        if ts:   bits.append(f"strip={ts['strip']} rewrite={ts['rewrite']}")
        return " · ".join(bits) if bits else "[green]listo[/green]"
    return s


def _plan_sheet(manifest: Manifest, item: Item, state: State,
                account: Optional[str]) -> dict:
    local_path = manifest.root / item.local
    snapshot = state.get_sheet(item.local)
    local_matrix = sh.read_csv_matrix(local_path, item.key_column)
    remote = sh.fetch_remote_sheet(item, account)
    diff = sh.diff_sheet(snapshot, local_matrix, remote)

    if diff.struct_drift:
        return {
            "local": item.local, "type": "sheet",
            "status": "struct_drift",
            "struct_drift": diff.struct_drift,
            "drift_decision": "pending",
        }

    auto_merge = []
    pending = []
    for c in diff.cells:
        base = {
            "row_key": c.row_key, "column": c.column,
            "snapshot": c.snapshot, "local": c.local, "remote": c.remote,
        }
        if c.classification == "push":
            auto_merge.append({**base, "action": "push"})
        elif c.classification == "pull_formula":
            auto_merge.append({**base, "action": "pull_formula", "formula": c.formula})
        else:
            pending.append({**base, "kind": c.classification,
                             "formula": c.formula or None, "decision": "pending"})

    comments = sh.fetch_threaded_comments(item.drive_id, account) if pending else []
    status = "noop" if not auto_merge and not pending \
             and not diff.local_only_rows and not diff.remote_only_rows else "ok"

    return {
        "local": item.local, "type": "sheet", "status": status,
        "auto_merge": auto_merge, "pending": pending,
        "comments_context": comments,
        "local_only_rows": diff.local_only_rows,
        "remote_only_rows": diff.remote_only_rows,
        "remote_modified_time": remote.modified_time,
        "tab_title": remote.tab_title,
        "headers": remote.matrix.headers,
        "remote_row_order": remote.matrix.row_order,
    }


def _plan_doc(manifest: Manifest, item: Item, state: State,
              account: Optional[str]) -> dict:
    local_path = manifest.root / item.local
    snapshot = state.get_doc(item.local)
    local_h = file_hash(local_path)
    remote_mt = fetch_doc_modified_time(item.drive_id, account)

    if snapshot.remote_modified_time and remote_mt > snapshot.remote_modified_time:
        return {
            "local": item.local, "type": "doc", "status": "doc_drift",
            "drift_reason": f"Doc remoto editado: {snapshot.remote_modified_time} → {remote_mt}",
            "drift_decision": "pending",
        }
    if snapshot.local_hash == local_h:
        return {"local": item.local, "type": "doc", "status": "noop"}

    transform_names = [t.name for t in item.transforms]
    result = apply_md_transforms(local_path, manifest, transform_names)
    preview_path = manifest.preview_dir / item.local
    preview_path.parent.mkdir(parents=True, exist_ok=True)
    preview_path.write_text(result.text)

    return {
        "local": item.local, "type": "doc", "status": "ok",
        "transforms_summary": {
            "strip": result.strip_count, "rewrite": result.rewrite_count,
            "unresolved": result.unresolved_links,
        },
        "preview_path": str(preview_path.relative_to(manifest.root)),
        "remote_modified_time": remote_mt,
        "local_hash": local_h,
    }


# =====================================================================
#  APPLY
# =====================================================================

def cmd_apply(root: Path, only=None, account: Optional[str] = None) -> int:
    manifest = load_manifest(root)
    state = State(manifest.state_path)

    if not manifest.decisions_path.exists():
        console.print("[red]No hay decisions.yaml — corre `cowork sync plan` primero.[/red]")
        return 1

    decisions = read_decisions(manifest.decisions_path)
    account = account or decisions.get("account")
    pending = has_pending(decisions)
    if pending:
        console.print(f"[red]{len(pending)} decisiones pending — resolvé decisions.yaml:[/red]")
        for p in pending[:10]:
            console.print(f"  · {p}")
        return 1

    only_set = set(only or [])
    # Obtener access token una vez (para Docs)
    _access_token: Optional[str] = None

    for entry in decisions["items"]:
        if only_set and entry["local"] not in only_set:
            continue
        if entry["status"] not in ("ok",):
            if entry["status"] != "noop":
                console.print(f"[yellow]skip {entry['local']} (status={entry['status']})[/yellow]")
            continue

        item = manifest.find_item(entry["local"])
        if item is None:
            console.print(f"[red]Item {entry['local']} no está en el manifiesto[/red]"); continue

        if item.type == "sheet":
            _apply_sheet(item, entry, state, account, manifest_root=manifest.root)
        elif item.type == "doc":
            if _access_token is None and account:
                from .auth import get_access_token
                try:
                    _access_token = get_access_token(account)
                except Exception as e:
                    console.print(f"[red]No se pudo obtener access token: {e}[/red]"); return 1
            _apply_doc(manifest, item, entry, state, account, _access_token)
        console.print(f"[green]✓[/green] {item.local}")

    state.save()
    console.print(f"\n[bold green]apply completado[/bold green] — state actualizado.")
    return 0


def _apply_sheet(item: Item, entry: dict, state: State,
                 account: Optional[str], manifest_root: Optional[Path] = None) -> None:
    # Re-fetch remoto para validar carrera
    remote = sh.fetch_remote_sheet(item, account)
    if entry.get("remote_modified_time") and remote.modified_time != entry["remote_modified_time"]:
        console.print(f"[yellow]Race en {item.local}: remoto cambió desde plan. Skip.[/yellow]")
        return

    csv_abs = (manifest_root / item.local) if manifest_root else Path(item.local)
    local_matrix = sh.read_csv_matrix(csv_abs, item.key_column)

    headers = entry.get("headers", remote.matrix.headers)
    tab_title = entry.get("tab_title", remote.tab_title)
    remote_row_order = entry.get("remote_row_order", remote.matrix.row_order)

    push_updates: list[tuple[str, str, str]] = []
    pullback: list[tuple[str, str, str]] = []

    for am in entry.get("auto_merge", []):
        if am["action"] == "push":
            push_updates.append((am["row_key"], am["column"], am["local"]))
        elif am["action"] == "pull_formula":
            pullback.append((am["row_key"], am["column"], am["remote"]))

    for p in entry.get("pending", []):
        d = p.get("decision", "skip")
        if d == "local":
            push_updates.append((p["row_key"], p["column"], p["local"]))
        elif d == "remote":
            pullback.append((p["row_key"], p["column"], p["remote"]))

    if push_updates:
        sh.apply_cell_updates(item.drive_id, tab_title, headers,
                              remote_row_order, item, push_updates,
                              local_matrix.rows, account)

    if pullback:
        # Aplicar write-back al CSV local
        # local_matrix puede estar desactualizado; usar root del manifiesto
        for rk, col, val in pullback:
            if rk in local_matrix.rows:
                local_matrix.rows[rk][col] = val
        # Necesitamos la ruta absoluta; la recuperamos del manifest a través del entry
        if csv_abs.exists():
            sh.write_csv_matrix(csv_abs, local_matrix)

    # Snapshot final
    final = sh.fetch_remote_sheet(item, account)
    state.set_sheet(item.local, SheetSnapshot(
        headers=final.matrix.headers,
        rows=final.matrix.rows,
        remote_modified_time=final.modified_time,
        applied_at=now_iso(),
        values_hash=matrix_hash(final.matrix.headers, final.matrix.rows),
    ))


def _apply_doc(manifest: Manifest, item: Item, entry: dict, state: State,
               account: Optional[str], access_token: Optional[str]) -> None:
    preview_path = manifest.root / entry["preview_path"]
    docx_path = md_to_docx(preview_path)
    new_mt = update_doc_content(item.drive_id, docx_path, account, access_token)
    state.set_doc(item.local, DocSnapshot(
        remote_modified_time=new_mt,
        local_hash=entry["local_hash"],
        applied_at=now_iso(),
    ))


