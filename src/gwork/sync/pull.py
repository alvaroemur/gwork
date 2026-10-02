"""Pull one Doc tab into its local Markdown file (Doc → Markdown).

Default is a read-only diff. `--apply` writes the file after saving a backup
of the existing one under ``.gwork/backups/``, then re-baselines the tab.
Formatting beyond headings, lists, bold, italic, strikethrough, inline code,
links, and tables is not carried over; images become a ``<!-- image -->`` note.
"""

from __future__ import annotations

import difflib
import re
import shutil
from pathlib import Path
from typing import Optional

from rich.console import Console

from . import baseline as bl
from .decisions import now_iso
from .gog import docs_raw
from .manifest import load_manifest
from .state import DocSnapshot, State, file_hash

console = Console()

_HEADING_PREFIX = {
    "TITLE": "# ", "SUBTITLE": "## ",
    "HEADING_1": "# ", "HEADING_2": "## ", "HEADING_3": "### ",
    "HEADING_4": "#### ", "HEADING_5": "##### ", "HEADING_6": "###### ",
}
_MONO = ("courier", "consolas", "roboto mono", "source code", "monospace")


def _is_numbered(raw: dict, paragraph: dict) -> bool:
    bullet = paragraph.get("bullet") or {}
    lst = (raw.get("lists") or {}).get(bullet.get("listId", ""), {})
    levels = (lst.get("listProperties") or {}).get("nestingLevels") or []
    level = bullet.get("nestingLevel", 0)
    if level < len(levels):
        return bool(levels[level].get("glyphType", "").startswith(("DECIMAL", "ALPHA", "ROMAN")))
    return False


def _wrap(text: str, style: dict) -> str:
    if not text.strip():
        return text
    lead = text[: len(text) - len(text.lstrip())]
    trail = text[len(text.rstrip()):]
    core = text.strip()
    font = ((style.get("weightedFontFamily") or {}).get("fontFamily") or "").lower()
    if any(m in font for m in _MONO):
        core = f"`{core}`"
    if style.get("strikethrough"):
        core = f"~~{core}~~"
    if style.get("italic"):
        core = f"*{core}*"
    if style.get("bold"):
        core = f"**{core}**"
    url = (style.get("link") or {}).get("url")
    if url:
        core = f"[{core}]({url})"
    return f"{lead}{core}{trail}"


def _inline_md(paragraph: dict) -> str:
    out = []
    for el in paragraph.get("elements", []) or []:
        run = el.get("textRun")
        if run:
            content = (run.get("content") or "").replace("\x0b", "  \n")
            out.append(_wrap(content.rstrip("\n"), run.get("textStyle") or {}))
        elif "inlineObjectElement" in el:
            out.append("<!-- image -->")
    return "".join(out).strip()


def _escape_cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def raw_to_markdown(raw: dict) -> str:
    """Render a `docs raw --tab` response as Markdown."""
    parts: list[str] = []
    list_run: list[str] = []

    def flush_list() -> None:
        if list_run:
            parts.append("\n".join(list_run))
            list_run.clear()

    for element in (raw.get("body", {}) or {}).get("content", []) or []:
        paragraph = element.get("paragraph")
        if paragraph:
            text = _inline_md(paragraph)
            if not text:
                flush_list()
                continue
            if paragraph.get("bullet"):
                level = paragraph["bullet"].get("nestingLevel", 0)
                marker = "1." if _is_numbered(raw, paragraph) else "-"
                list_run.append(f"{'  ' * level}{marker} {text}")
                continue
            flush_list()
            style = (paragraph.get("paragraphStyle") or {}).get("namedStyleType", "")
            parts.append(_HEADING_PREFIX.get(style, "") + text)
            continue
        table = element.get("table")
        if table:
            flush_list()
            rows = []
            for row in table.get("tableRows", []) or []:
                cells = []
                for cell in row.get("tableCells", []) or []:
                    texts = [_inline_md(c["paragraph"]) for c in cell.get("content", []) or []
                             if c.get("paragraph")]
                    cells.append(_escape_cell(" ".join(t for t in texts if t)))
                rows.append("| " + " | ".join(cells) + " |")
            if rows:
                width = rows[0].count(" | ") + 1
                rows.insert(1, "|" + "|".join([" --- "] * width) + "|")
                parts.append("\n".join(rows))
    flush_list()
    return "\n\n".join(parts) + "\n"


def cmd_pull(root: Path, only: list[str], account: Optional[str] = None,
             do_apply: bool = False) -> int:
    manifest = load_manifest(root)
    account = manifest.account_for_gog(account)
    state = State(manifest.state_path)
    if not only:
        console.print("[red]pull needs --only <path|resource> (one tab at a time).[/red]")
        return 2
    try:
        items = manifest.select_items(only)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        return 2
    if len(items) != 1 or items[0].type != "doc":
        console.print("[red]pull works on exactly one Doc tab.[/red]")
        return 2
    item = items[0]
    local_path = manifest.root / item.local

    raw = docs_raw(item.drive_id, tab_id=item.doc_tab, account=account)
    remote_md = raw_to_markdown(raw)
    current = local_path.read_text(encoding="utf-8") if local_path.exists() else ""
    diff = "".join(difflib.unified_diff(
        current.splitlines(keepends=True), remote_md.splitlines(keepends=True),
        fromfile=f"local:{item.local}", tofile=f"drive:{item.drive_id}/{item.doc_tab}",
    ))
    if not diff:
        console.print(f"[green]{item.local}[/green] already matches Drive (as Markdown).")
    else:
        console.print(diff)
    if bl.has_inline_objects(raw):
        console.print("[yellow]The tab holds images: they appear as `<!-- image -->` "
                      "and are not downloaded.[/yellow]")
    if not do_apply:
        console.print("\n[dim]Read-only. Re-run with --apply to overwrite the local "
                      "file (a backup is kept).[/dim]")
        return 0
    if not diff:
        return 0

    stamp = re.sub(r"[^0-9A-Za-z]", "", now_iso())
    if local_path.exists():
        backup = manifest.root / ".gwork" / "backups" / f"{item.local.replace('/', '__')}.{stamp}"
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(local_path, backup)
        console.print(f"[dim]backup → {backup.relative_to(manifest.root)}[/dim]")
    local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_text(remote_md, encoding="utf-8")

    lines = bl.blocks_from_raw(raw)
    captured = now_iso()
    h = bl.blocks_hash(lines)
    bl.save_baseline(manifest.root, item.local, bl.Baseline(
        drive_id=item.drive_id, tab_id=item.doc_tab, captured_at=captured,
        blocks=lines, hash=h, has_images=bl.has_inline_objects(raw),
    ))
    state.set_doc(item.local, DocSnapshot(
        remote_modified_time=None, local_hash=file_hash(local_path),
        applied_at=captured, baseline_hash=h,
    ))
    state.save()
    console.print(f"[green]✓[/green] {item.local} written from Drive; baseline updated.")
    return 0
