"""Per-tab baselines and a normalized block model for Docs.

A Doc has one `modifiedTime` for all its tabs, so it cannot tell which tab
changed. This module fingerprints each tab by content instead. Both sides
(remote tab and local Markdown) reduce to the same list of normalized lines, so
they can be compared, hashed, and diffed with the same code.

Line format: ``KIND|text``. ``KIND`` is ``TITLE``, ``H1``..``H6``, ``LIST`` or
``P``. Table rows use ``T|cell|cell``. Inline images are ignored in the text and
reported separately through :func:`has_inline_objects`.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import docs_ast
from .docs_ast import Paragraph, Table
from .gog import docs_raw

_QUOTES = str.maketrans({
    "‘": "'", "’": "'", "“": '"', "”": '"',
    " ": " ", "–": "-", "—": "-",
})
_WS = re.compile(r"\s+")

_HEADING_KIND = {
    "TITLE": "TITLE", "SUBTITLE": "TITLE",
    "HEADING_1": "H1", "HEADING_2": "H2", "HEADING_3": "H3",
    "HEADING_4": "H4", "HEADING_5": "H5", "HEADING_6": "H6",
}


def normalize_text(text: str) -> str:
    return _WS.sub(" ", text.translate(_QUOTES).replace("\x0b", " ")).strip()


# ---------------------------------------------------------------------------
# Remote tab → lines
# ---------------------------------------------------------------------------

def _paragraph_text(paragraph: dict) -> str:
    return "".join(
        (el.get("textRun") or {}).get("content", "")
        for el in paragraph.get("elements", []) or []
    )


def _element_lines(element: dict) -> list[str]:
    paragraph = element.get("paragraph")
    if paragraph:
        text = normalize_text(_paragraph_text(paragraph))
        if not text:
            return []
        style = (paragraph.get("paragraphStyle") or {}).get("namedStyleType", "")
        if style in _HEADING_KIND:
            kind = _HEADING_KIND[style]
        elif paragraph.get("bullet"):
            kind = "LIST"
        else:
            kind = "P"
        return [f"{kind}|{text}"]
    table = element.get("table")
    if table:
        out = []
        for row in table.get("tableRows", []) or []:
            cells = []
            for cell in row.get("tableCells", []) or []:
                parts = []
                for child in cell.get("content", []) or []:
                    p = child.get("paragraph")
                    if p:
                        t = normalize_text(_paragraph_text(p))
                        if t:
                            parts.append(t)
                cells.append(" ".join(parts))
            out.append("T|" + "|".join(cells))
        return out
    return []


def blocks_from_raw(raw: dict) -> list[str]:
    """Normalize a `docs raw --tab` response into comparable lines."""
    content = (raw.get("body", {}) or {}).get("content", []) or []
    lines: list[str] = []
    for element in content:
        lines.extend(_element_lines(element))
    return lines


def has_inline_objects(raw: dict) -> bool:
    """True when the tab body holds inline images or other inline objects."""
    def scan(elements: list) -> bool:
        for el in elements:
            paragraph = el.get("paragraph")
            if paragraph:
                for run in paragraph.get("elements", []) or []:
                    if "inlineObjectElement" in run:
                        return True
            table = el.get("table")
            if table:
                for row in table.get("tableRows", []) or []:
                    for cell in row.get("tableCells", []) or []:
                        if scan(cell.get("content", []) or []):
                            return True
        return False

    return scan((raw.get("body", {}) or {}).get("content", []) or [])


# ---------------------------------------------------------------------------
# Local Markdown → lines
# ---------------------------------------------------------------------------

def _paragraph_line(p: Paragraph) -> str:
    text = normalize_text(p.text)
    if not text:
        return ""
    kind = _HEADING_KIND.get(p.named_style) or ("LIST" if p.bullet else "P")
    return f"{kind}|{text}"


def blocks_from_model(blocks: list) -> list[str]:
    lines: list[str] = []
    for block in blocks:
        if isinstance(block, Table):
            for row in block.rows:
                cells = []
                for cell in row:
                    parts = [normalize_text(p.text) for p in cell]
                    cells.append(" ".join(t for t in parts if t))
                lines.append("T|" + "|".join(cells))
        elif isinstance(block, Paragraph):
            line = _paragraph_line(block)
            if line:
                lines.append(line)
    return lines


def blocks_from_markdown(text: str) -> list[str]:
    return blocks_from_model(docs_ast.markdown_to_blocks(text))


# ---------------------------------------------------------------------------
# Hash, diff
# ---------------------------------------------------------------------------

def blocks_hash(lines: list[str]) -> str:
    h = hashlib.sha256()
    h.update(json.dumps(lines, ensure_ascii=False).encode())
    return f"sha256:{h.hexdigest()}"


@dataclass
class DiffSummary:
    added: int = 0      # lines present only in the target
    removed: int = 0    # lines present only in the source
    changed: int = 0    # replaced lines (paired)
    tables: int = 0     # table rows touched (also counted above)

    @property
    def total(self) -> int:
        return self.added + self.removed + self.changed

    def as_dict(self) -> dict:
        return {"added": self.added, "removed": self.removed,
                "changed": self.changed, "tables": self.tables}

    def label(self) -> str:
        if not self.total:
            return "sin cambios"
        bits = [f"+{self.added}", f"−{self.removed}", f"~{self.changed}"]
        if self.tables:
            bits.append(f"tablas:{self.tables}")
        return " ".join(bits)


def diff_blocks(source: list[str], target: list[str]) -> DiffSummary:
    """Summarize what turns ``source`` into ``target`` (paragraph level)."""
    summary = DiffSummary()
    matcher = difflib.SequenceMatcher(a=source, b=target, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        touched = source[i1:i2] + target[j1:j2]
        summary.tables += sum(1 for ln in touched if ln.startswith("T|"))
        if tag == "delete":
            summary.removed += i2 - i1
        elif tag == "insert":
            summary.added += j2 - j1
        else:
            paired = min(i2 - i1, j2 - j1)
            summary.changed += paired
            summary.removed += (i2 - i1) - paired
            summary.added += (j2 - j1) - paired
    return summary


def unified_block_diff(source: list[str], target: list[str],
                       source_label: str, target_label: str) -> str:
    return "\n".join(difflib.unified_diff(
        source, target, fromfile=source_label, tofile=target_label, lineterm="",
    ))


# ---------------------------------------------------------------------------
# Baseline storage
# ---------------------------------------------------------------------------

def baseline_path(manifest_root: Path, local: str) -> Path:
    return manifest_root / ".gwork" / "baseline" / (local.replace("/", "__") + ".json")


@dataclass
class Baseline:
    drive_id: str
    tab_id: Optional[str]
    captured_at: str
    blocks: list[str]
    hash: str
    has_images: bool = False


def save_baseline(manifest_root: Path, local: str, baseline: Baseline) -> Path:
    path = baseline_path(manifest_root, local)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "local": local, "drive_id": baseline.drive_id, "tab_id": baseline.tab_id,
        "captured_at": baseline.captured_at, "hash": baseline.hash,
        "has_images": baseline.has_images, "blocks": baseline.blocks,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def load_baseline(manifest_root: Path, local: str) -> Optional[Baseline]:
    path = baseline_path(manifest_root, local)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return Baseline(
        drive_id=data["drive_id"], tab_id=data.get("tab_id"),
        captured_at=data.get("captured_at", ""), blocks=data["blocks"],
        hash=data["hash"], has_images=bool(data.get("has_images")),
    )


def capture_remote(drive_id: str, tab_id: Optional[str],
                   account: Optional[str]) -> tuple[list[str], str, bool]:
    """Read one tab and return (lines, hash, has_inline_objects)."""
    raw = docs_raw(drive_id, tab_id=tab_id, account=account)
    lines = blocks_from_raw(raw)
    return lines, blocks_hash(lines), has_inline_objects(raw)


# ---------------------------------------------------------------------------
# Assessment
# ---------------------------------------------------------------------------

def assess_tab(local_lines: list[str], remote_lines: list[str],
               baseline: Optional[Baseline]) -> dict:
    """Classify one tab. Returns state, hashes and a local→remote diff summary.

    States: ``in_sync`` (nothing to push), ``no_baseline``, ``drift`` (remote edited after the
    baseline and differs from local) and ``local_ahead`` (ready to push).
    """
    remote_hash = blocks_hash(remote_lines)
    summary = diff_blocks(remote_lines, local_lines)
    out = {
        "remote_hash": remote_hash,
        "baseline_hash": baseline.hash if baseline else None,
        "diff": summary.as_dict(),
        "diff_label": summary.label(),
    }
    if not summary.total:
        out["state"] = "in_sync"
    elif baseline is None:
        out["state"] = "no_baseline"
    elif remote_hash != baseline.hash:
        out["state"] = "drift"
        out["remote_vs_baseline"] = diff_blocks(baseline.blocks, remote_lines).as_dict()
    else:
        out["state"] = "local_ahead"
    return out
