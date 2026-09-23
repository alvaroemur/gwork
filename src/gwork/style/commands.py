from __future__ import annotations

"""Commands for ``gwork style`` and top-level ``gwork init``."""

import tempfile
from pathlib import Path
from typing import Optional

import yaml
from rich.console import Console
from rich.table import Table

from ..sync import gog
from .engine import StyleSyncEngine
from .introspect import extract_style_tokens, template_markdown
from .manifest import MANIFEST_NAME, StyleManifest
from .requests_builder import build_requests
from .seed import seed_document
from .tokens import parse_pt

console = Console()


def _load(manifest_path: Path, account: Optional[str]) -> tuple:
    manifest = StyleManifest.load(Path(manifest_path))
    return manifest, account or manifest.account


def _tab_id(tab: dict) -> str:
    return tab.get("id") or tab.get("tabId") or tab.get("tab_id", "")


def _tab_title(tab: dict) -> str:
    return tab.get("title") or tab.get("name") or _tab_id(tab)


def _resolve_tabs(manifest: StyleManifest, account: Optional[str],
                  target_tab: Optional[str] = None) -> list:
    tabs = [
        {"id": _tab_id(t), "title": _tab_title(t)}
        for t in manifest.tabs
        if _tab_id(t)
    ]
    if not tabs:
        tabs = [
            {"id": _tab_id(t), "title": _tab_title(t)}
            for t in gog.docs_list_tabs(manifest.doc_id, account)
            if _tab_id(t)
        ]
    if target_tab:
        matched = [t for t in tabs if t["id"] == target_tab or t["title"] == target_tab]
        return matched or [{"id": target_tab, "title": target_tab}]
    return tabs


def _ensure_template_tab(manifest: StyleManifest, account: Optional[str]) -> dict:
    tabs = gog.docs_list_tabs(manifest.doc_id, account)
    existing = next(
        (tab for tab in tabs if _tab_title(tab) == manifest.template_tab),
        None,
    )
    if existing:
        return {"id": _tab_id(existing), "title": _tab_title(existing)}
    created = gog.docs_add_tab(manifest.doc_id, manifest.template_tab, account)
    created_id = (
        _tab_id(created)
        or _tab_id((created.get("tab", {}) if isinstance(created, dict) else {}))
        or _tab_id((created.get("tabProperties", {}) if isinstance(created, dict) else {}))
    )
    if created_id:
        return {"id": created_id, "title": manifest.template_tab}
    tabs = gog.docs_list_tabs(manifest.doc_id, account)
    created_tab = next(tab for tab in tabs if _tab_title(tab) == manifest.template_tab)
    return {"id": _tab_id(created_tab), "title": manifest.template_tab}


def refresh_template(manifest: StyleManifest, account: Optional[str]) -> dict:
    """Extract live tokens, persist them, and rebuild the template tab."""
    if not manifest.doc_id:
        raise ValueError("The manifest does not identify a Google Doc")
    source_tabs = [
        tab
        for tab in _resolve_tabs(manifest, account)
        if tab["title"] != manifest.template_tab
    ]
    if not source_tabs:
        raise ValueError("The document has no source tab to inspect")
    documents = [
        gog.docs_raw(manifest.doc_id, tab_id=tab["id"], account=account)
        for tab in source_tabs
    ]
    tokens = extract_style_tokens(documents)
    template_tab = _ensure_template_tab(manifest, account)
    manifest.write_tokens(tokens, template_tab["id"])

    with tempfile.NamedTemporaryFile("w", suffix=".md", encoding="utf-8", delete=False) as handle:
        template_path = Path(handle.name)
        handle.write(template_markdown(tokens))
    try:
        gog.docs_write_markdown(
            manifest.doc_id,
            template_tab["id"] or template_tab["title"],
            template_path,
            account,
        )
    finally:
        template_path.unlink(missing_ok=True)

    raw = gog.docs_raw(
        manifest.doc_id,
        tab_id=template_tab["id"],
        account=account,
    )
    plan = StyleSyncEngine(manifest).analyze(
        raw,
        template_tab["id"],
        template_tab["title"],
    )
    requests = build_requests(
        plan,
        template_tab["id"],
        restore_table_widths=manifest.guard("auto_restore_table_widths"),
        cell_padding=_table_padding(manifest),
    )
    if requests:
        gog.batch_execute(
            manifest.doc_id,
            requests,
            account=account,
            source="gwork.style.template",
        )
    return {
        "tokens": tokens,
        "template_tab_id": template_tab["id"],
        "source_tabs": len(source_tabs),
        "requests": len(requests),
    }


def cmd_manifest_init(manifest_path: Path, doc_id: str,
                      account: Optional[str] = None) -> int:
    """Create or update a manifest from an existing Google Doc."""
    path = Path(manifest_path)
    if path.is_dir():
        path = path / MANIFEST_NAME
    data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    data = data or {}
    data.setdefault("version", 1)
    transport = data.setdefault("transport", {})
    transport.setdefault("provider", "gog")
    if account:
        transport["account"] = account
    data.setdefault("items", [])
    style = data.setdefault("style", {})
    style["document_id"] = doc_id
    style.setdefault("template_tab", "_template")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    manifest, resolved_account = _load(path, account)
    result = refresh_template(manifest, resolved_account)
    console.print(
        f"[green]Initialized[/green] {path} from {result['source_tabs']} tab(s); "
        f"template: {result['template_tab_id']}"
    )
    return 0


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
              tab: Optional[str] = None, refresh: bool = True) -> int:
    manifest, account = _load(manifest_path, account)
    if refresh:
        result = refresh_template(manifest, account)
        console.print(
            f"[green]Extracted tokens[/green] from {result['source_tabs']} tab(s); "
            f"updated {manifest.template_tab}."
        )

    tabs = _resolve_tabs(manifest, account, tab)
    if tab is None:
        tabs = [item for item in tabs if item["title"] != manifest.template_tab]
    table = Table(title="design system compliance")
    for column in ("tab", "id", "links", "dividers", "status"):
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
            "[green]compliant[/green]" if issues == 0 else f"[yellow]{issues} deviations[/yellow]",
        )
    console.print(table)

    if total_issues == 0:
        console.print("[green]The document complies with the design system.[/green]")
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
    console.print(f"[bold]plan · {manifest.doc_id}[/bold] — dry run; writes nothing")

    for tab_info in _resolve_tabs(manifest, account, tab):
        plan = _analyze(manifest, account, tab_info)
        _print_plan(manifest, plan)
    return 0


def _print_plan(manifest: StyleManifest, plan: dict) -> None:
    layout = plan["page_layout"]
    console.print(f"\n[bold]{plan['tab_title']}[/bold] ([dim]{plan['tab_id']}[/dim])")
    console.print(
        f"  · page: {layout['size']} with margins {layout['margins']} "
        f"(printable width {layout['printable_width']}pt)"
    )
    console.print(f"  · preserved links: {len(plan['links_preserved'])}")
    console.print(f"  · dividers to remove: {len(plan['dividers_to_remove'])}")
    console.print(f"  · paragraphs to format: {len(plan['paragraph_updates'])}")
    console.print(f"  · callouts: {len(plan['callout_updates'])}")
    console.print(f"  · text ranges: {len(plan['text_updates'])}")
    console.print(f"  · tables: {len(plan['table_updates'])}")
    for t in plan["table_updates"]:
        console.print(
            f"     - table #{t['table_index']}: {t['rows']}x{t['columns']} · "
            f"widths {t['target_widths']} · pin header {t['pin_header']}"
        )
    requests = build_requests(
        plan, plan["tab_id"],
        restore_table_widths=manifest.guard("auto_restore_table_widths"),
        cell_padding=_table_padding(manifest),
    )
    console.print(f"  · batchUpdate requests: [bold]{len(requests)}[/bold]")


# =====================================================================
#  APPLY
# =====================================================================

def cmd_apply(manifest_path: Path, account: Optional[str] = None,
              tab: Optional[str] = None, dry_run: bool = False) -> int:
    manifest, account = _load(manifest_path, account)
    if not manifest.doc_id:
        console.print("[red]The manifest does not identify a document.[/red]")
        return 1

    console.print(f"[bold]apply · {manifest.doc_id}[/bold]")
    tabs = _resolve_tabs(manifest, account, tab)

    if manifest.guard("inspect_diff_before_write"):
        console.print("[dim]guard inspect_diff_before_write: reviewing the plan…[/dim]")
        for tab_info in tabs:
            _print_plan(manifest, _analyze(manifest, account, tab_info))
        if dry_run:
            console.print("\n[yellow]dry run: nothing was written.[/yellow]")
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
        console.print("  1/4 page and margins")

        # Phase 1: apply structural mutations in reverse order to preserve indices.
        if manifest.guard("remove_dash_dividers"):
            dividers = _analyze(manifest, account, tab_info)["dividers_to_remove"]
            for d in sorted(dividers, key=lambda x: x["start"], reverse=True):
                gog.docs_delete_range(manifest.doc_id, tab_id, d["start"], d["end"],
                                      account=account)
            console.print(f"  2/4 dividers removed: {len(dividers)}")
        else:
            console.print("  2/4 guard remove_dash_dividers disabled")

        # Phase 2: read fresh state; styles do not shift indices within the batch.
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
            console.print("  3/4 no pending style changes")

        pinned = 0
        for tbl in plan["table_updates"]:
            if tbl["pin_header"]:
                gog.docs_pin_table_header(manifest.doc_id, tab_id,
                                          table_index=tbl["table_index"], rows=1,
                                          account=account)
                pinned += 1
        console.print(f"  4/4 pinned headers: {pinned}")

    console.print("\n[bold green]apply complete[/bold green]")
    return 0


# =====================================================================
#  INIT
# =====================================================================

def cmd_init(manifest_path: Path, title: str, account: Optional[str] = None,
             parent: Optional[str] = None, source: Optional[Path] = None,
             write_back: bool = False) -> int:
    """Create a Doc seeded with the manifest's ``namedStyles``.

    This is the only way to apply brand tokens to HEADING_1 and related styles.
    The Docs API has no ``updateNamedStyles``, so an existing document cannot
    redefine them; ``apply`` can only overlay styles.
    """
    manifest, account = _load(manifest_path, account)
    console.print(f"[bold]init[/bold] — seeding namedStyles in a new Doc: {title}")

    result = seed_document(manifest, title=title, md_path=Path(source) if source else None,
                           parent=parent, account=account)
    doc_id = result.get("id") or (result.get("file", {}) or {}).get("id", "")
    url = f"https://docs.google.com/document/d/{doc_id}/edit" if doc_id else ""
    console.print(f"[green]✓[/green] document created: {doc_id}")
    if url:
        console.print(f"  {url}")
    console.print(
        "[yellow]Note:[/yellow] .docx supports only binary bold. Numeric weights "
        "(weight: 900) import as 400 + bold; exact weights still require an "
        "overlay from `gwork style apply`."
    )

    if write_back and doc_id and manifest.path:
        manifest.path.write_text(
            write_doc_id(manifest.path.read_text(encoding="utf-8"), doc_id),
            encoding="utf-8",
        )
        console.print(f"[green]✓[/green] wrote doc_id to {manifest.path}")
    return 0


def write_doc_id(text: str, doc_id: str) -> str:
    """Set ``style.document_id`` without replacing unrelated YAML data."""
    data = yaml.safe_load(text) or {}
    data.setdefault("style", {})["document_id"] = doc_id
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
