from __future__ import annotations

"""Comandos de `cowork style`: audit, plan, apply, init."""

import re
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.table import Table

from ..sync import gog
from .engine import StyleSyncEngine
from .manifest import StyleManifest
from .requests_builder import build_requests
from .seed import seed_document
from .tokens import parse_pt

console = Console()


def _load(manifest_path: Path, account: Optional[str]) -> tuple:
    manifest = StyleManifest.load(Path(manifest_path))
    return manifest, account or manifest.account


def _resolve_tabs(manifest: StyleManifest, account: Optional[str],
                  target_tab: Optional[str] = None) -> list:
    tabs = [{"id": t["id"], "title": t.get("title", t["id"])} for t in manifest.tabs]
    if not tabs:
        tabs = [{"id": t["id"], "title": t.get("title", t["id"])}
                for t in gog.docs_list_tabs(manifest.doc_id, account)]
    if target_tab:
        matched = [t for t in tabs if t["id"] == target_tab or t["title"] == target_tab]
        return matched or [{"id": target_tab, "title": target_tab}]
    return tabs


def _analyze(manifest: StyleManifest, account: Optional[str], tab: dict) -> dict:
    raw = gog.docs_raw(manifest.doc_id, tab_id=tab["id"], account=account)
    return StyleSyncEngine(manifest).analyze(raw, tab["id"], tab["title"])


def _table_padding(manifest: StyleManifest) -> dict:
    padding = (manifest.components.get("tables", {}) or {}).get("padding", {}) or {}
    return {
        "top": parse_pt(padding.get("top", "3.5pt")) or 3.5,
        "bottom": parse_pt(padding.get("bottom", "3.5pt")) or 3.5,
        "left": parse_pt(padding.get("left", "4.5pt")) or 4.5,
        "right": parse_pt(padding.get("right", "4.5pt")) or 4.5,
    }


# =====================================================================
#  AUDIT
# =====================================================================

def cmd_audit(manifest_path: Path, account: Optional[str] = None,
              tab: Optional[str] = None) -> int:
    manifest, account = _load(manifest_path, account)
    console.print(f"[bold]audit · {manifest.doc_id}[/bold] — cuenta: {account or 'default'}")

    tabs = _resolve_tabs(manifest, account, tab)
    table = Table(title="cumplimiento del sistema de diseño")
    for column in ("pestaña", "id", "enlaces", "separadores", "estado"):
        table.add_column(column)

    plans = []
    total_issues = 0
    for tab_info in tabs:
        plan = _analyze(manifest, account, tab_info)
        plans.append(plan)
        issues = len(plan["audit_issues"])
        total_issues += issues
        table.add_row(
            plan["tab_title"], plan["tab_id"],
            str(len(plan["links_preserved"])),
            str(len(plan["dividers_to_remove"])),
            "[green]conforme[/green]" if issues == 0 else f"[yellow]{issues} desviaciones[/yellow]",
        )
    console.print(table)

    if total_issues == 0:
        console.print("[green]El documento cumple con el sistema de diseño.[/green]")
        return 0

    for plan in plans:
        if not plan["audit_issues"]:
            continue
        console.print(f"\n[bold]{plan['tab_title']}[/bold] ([dim]{plan['tab_id']}[/dim])")
        for issue in plan["audit_issues"]:
            console.print(f"  · {issue}")
    return 0


# =====================================================================
#  PLAN
# =====================================================================

def cmd_plan(manifest_path: Path, account: Optional[str] = None,
             tab: Optional[str] = None) -> int:
    manifest, account = _load(manifest_path, account)
    console.print(f"[bold]plan · {manifest.doc_id}[/bold] — dry-run, no escribe nada")

    for tab_info in _resolve_tabs(manifest, account, tab):
        plan = _analyze(manifest, account, tab_info)
        _print_plan(manifest, plan)
    return 0


def _print_plan(manifest: StyleManifest, plan: dict) -> None:
    layout = plan["page_layout"]
    console.print(f"\n[bold]{plan['tab_title']}[/bold] ([dim]{plan['tab_id']}[/dim])")
    console.print(
        f"  · página: {layout['size']} con márgenes {layout['margins']} "
        f"(ancho útil {layout['printable_width']}pt)"
    )
    console.print(f"  · enlaces preservados: {len(plan['links_preserved'])}")
    console.print(f"  · separadores a purgar: {len(plan['dividers_to_remove'])}")
    console.print(f"  · párrafos a formatear: {len(plan['paragraph_updates'])}")
    console.print(f"  · callouts: {len(plan['callout_updates'])}")
    console.print(f"  · rangos de texto: {len(plan['text_updates'])}")
    console.print(f"  · tablas: {len(plan['table_updates'])}")
    for t in plan["table_updates"]:
        console.print(
            f"     - tabla #{t['table_index']}: {t['rows']}x{t['columns']} · "
            f"anchos {t['target_widths']} · pin header {t['pin_header']}"
        )
    requests = build_requests(
        plan, plan["tab_id"],
        restore_table_widths=manifest.guard("auto_restore_table_widths"),
        cell_padding=_table_padding(manifest),
    )
    console.print(f"  · requests de batchUpdate: [bold]{len(requests)}[/bold]")


# =====================================================================
#  APPLY
# =====================================================================

def cmd_apply(manifest_path: Path, account: Optional[str] = None,
              tab: Optional[str] = None, dry_run: bool = False) -> int:
    manifest, account = _load(manifest_path, account)
    if not manifest.doc_id:
        console.print("[red]El manifiesto no declara document.doc_id.[/red]")
        return 1

    console.print(f"[bold]apply · {manifest.doc_id}[/bold]")
    tabs = _resolve_tabs(manifest, account, tab)

    if manifest.guard("inspect_diff_before_write"):
        console.print("[dim]guard inspect_diff_before_write: revisando el plan…[/dim]")
        for tab_info in tabs:
            _print_plan(manifest, _analyze(manifest, account, tab_info))
        if dry_run:
            console.print("\n[yellow]dry-run: no se escribió nada.[/yellow]")
            return 0

    for tab_info in tabs:
        tab_id = tab_info["id"]
        console.print(f"\n[bold]▶ {tab_info['title']}[/bold] ([dim]{tab_id}[/dim])")

        gog.docs_page_layout(
            manifest.doc_id, tab_id=tab_id,
            size=manifest.page_layout.get("size", "Letter"),
            margins=manifest.page_layout.get("margins", {}),
            account=account,
        )
        console.print("  1/4 página y márgenes")

        # Fase 1: mutaciones estructurales, en orden inverso para no mover índices.
        if manifest.guard("remove_dash_dividers"):
            dividers = _analyze(manifest, account, tab_info)["dividers_to_remove"]
            for d in sorted(dividers, key=lambda x: x["start"], reverse=True):
                gog.docs_delete_range(manifest.doc_id, tab_id, d["start"], d["end"],
                                      account=account)
            console.print(f"  2/4 separadores purgados: {len(dividers)}")
        else:
            console.print("  2/4 guard remove_dash_dividers desactivado")

        # Fase 2: relectura fresca; los estilos no mueven índices dentro del lote.
        plan = _analyze(manifest, account, tab_info)
        requests = build_requests(
            plan, tab_id,
            restore_table_widths=manifest.guard("auto_restore_table_widths"),
            cell_padding=_table_padding(manifest),
        )
        if requests:
            result = gog.batch_execute(manifest.doc_id, requests, account=account)
            console.print(f"  3/4 batchUpdate: {len(requests)} requests → {result}")
        else:
            console.print("  3/4 sin cambios de estilo pendientes")

        pinned = 0
        for tbl in plan["table_updates"]:
            if tbl["pin_header"]:
                gog.docs_pin_table_header(manifest.doc_id, tab_id,
                                          table_index=tbl["table_index"], rows=1,
                                          account=account)
                pinned += 1
        console.print(f"  4/4 cabeceras fijadas: {pinned}")

    console.print("\n[bold green]apply completado[/bold green]")
    return 0


# =====================================================================
#  INIT
# =====================================================================

def cmd_init(manifest_path: Path, title: str, account: Optional[str] = None,
             parent: Optional[str] = None, source: Optional[Path] = None,
             write_back: bool = False) -> int:
    """Crea un Doc con los `namedStyles` del manifiesto ya sembrados.

    Es el único camino para que HEADING_1 y compañía lleven los tokens de marca:
    `updateNamedStyles` no existe en la Docs API, así que un documento ya creado
    no se puede redefinir — solo se le puede superponer estilo con `apply`.
    """
    manifest, account = _load(manifest_path, account)
    console.print(f"[bold]init[/bold] — sembrando namedStyles en un Doc nuevo: {title}")

    result = seed_document(manifest, title=title, md_path=Path(source) if source else None,
                           parent=parent, account=account)
    doc_id = result.get("id") or (result.get("file", {}) or {}).get("id", "")
    url = f"https://docs.google.com/document/d/{doc_id}/edit" if doc_id else ""
    console.print(f"[green]✓[/green] documento creado: {doc_id}")
    if url:
        console.print(f"  {url}")
    console.print(
        "[yellow]Nota:[/yellow] el .docx solo tiene negrita binaria. Los pesos "
        "numéricos (weight: 900) se importan como 400 + bold; el peso exacto "
        "sigue requiriendo overlay con `cowork style apply`."
    )

    if write_back and doc_id and manifest.path:
        manifest.path.write_text(
            write_doc_id(manifest.path.read_text(encoding="utf-8"), doc_id),
            encoding="utf-8",
        )
        console.print(f"[green]✓[/green] doc_id escrito en {manifest.path}")
    return 0


DOC_ID_LINE_RE = re.compile(r'^(\s*)doc_id:.*$', re.MULTILINE)


def write_doc_id(text: str, doc_id: str) -> str:
    """Fija `document.doc_id` en el YAML sin duplicar la clave."""
    if DOC_ID_LINE_RE.search(text):
        return DOC_ID_LINE_RE.sub(lambda m: f'{m.group(1)}doc_id: "{doc_id}"', text, count=1)
    return re.sub(r"^document:\s*$", f'document:\n  doc_id: "{doc_id}"', text,
                  count=1, flags=re.MULTILINE)
