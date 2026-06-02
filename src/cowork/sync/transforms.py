from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .manifest import Item, Manifest


@dataclass
class TransformResult:
    text: str
    strip_count: int = 0
    rewrite_count: int = 0
    unresolved_links: list[str] = None

    def __post_init__(self):
        if self.unresolved_links is None:
            self.unresolved_links = []


# Bloques internos: <!-- internal --> ... <!-- /internal -->
INTERNAL_RE = re.compile(
    r"[ \t]*<!--\s*internal\s*-->.*?<!--\s*/internal\s*-->[ \t]*\n?",
    re.DOTALL | re.IGNORECASE,
)

# Links markdown: [texto](path)
MD_LINK_RE = re.compile(r"(\[[^\]]+\])\(([^)]+)\)")


def strip_internal(text: str) -> tuple[str, int]:
    matches = INTERNAL_RE.findall(text)
    if not matches:
        # Validar que no haya open sin close
        if re.search(r"<!--\s*internal\s*-->", text, re.IGNORECASE):
            raise ValueError("Marcador <!-- internal --> sin cierre </!-- /internal -->")
        return text, 0
    cleaned = INTERNAL_RE.sub("", text)
    return cleaned, len(matches)


def _drive_url(item) -> str:
    if item.type == "sheet":
        return f"https://docs.google.com/spreadsheets/d/{item.drive_id}"
    if item.type == "doc":
        return f"https://docs.google.com/document/d/{item.drive_id}"
    if item.type == "slides":
        return f"https://docs.google.com/presentation/d/{item.drive_id}"
    return f"https://drive.google.com/file/d/{item.drive_id}"


def rewrite_links(text: str, manifest: Manifest, md_path: Path) -> tuple[str, int, list[str]]:
    """Reemplaza links relativos a .csv/.md por URLs de Drive según el manifiesto.

    md_path es la ruta absoluta del MD que se está transformando; los links se
    resuelven relativos al directorio que lo contiene.
    """
    rewrites = 0
    unresolved: list[str] = []
    base_dir = md_path.parent

    def repl(m: re.Match) -> str:
        nonlocal rewrites
        label, target = m.group(1), m.group(2)
        if target.startswith(("http://", "https://", "mailto:", "#")):
            return m.group(0)
        target_path = (base_dir / target).resolve()
        try:
            rel = target_path.relative_to(manifest.root)
        except ValueError:
            return m.group(0)
        item = manifest.find_item(str(rel))
        if item is None:
            if target.endswith((".csv", ".md")):
                unresolved.append(target)
            return m.group(0)
        rewrites += 1
        return f"{label}({_drive_url(item)})"

    out = MD_LINK_RE.sub(repl, text)
    return out, rewrites, unresolved


def apply_md_transforms(md_path: Path, manifest: Manifest, transform_names: list[str]) -> TransformResult:
    text = md_path.read_text()
    strip_count = 0
    rewrite_count = 0
    unresolved: list[str] = []
    for name in transform_names:
        if name == "strip_internal":
            text, n = strip_internal(text)
            strip_count += n
        elif name == "rewrite_links":
            text, n, u = rewrite_links(text, manifest, md_path)
            rewrite_count += n
            unresolved.extend(u)
        else:
            raise ValueError(f"Transform desconocido: {name}")
    return TransformResult(
        text=text,
        strip_count=strip_count,
        rewrite_count=rewrite_count,
        unresolved_links=unresolved,
    )


def doc_transform_names(manifest: Manifest, item: Item) -> list[str]:
    """Nombres de transform a aplicar antes de subir un Doc."""
    names = [t.name for t in item.transforms]
    if manifest.effective_link_mode(item) == "rewrite_to_drive":
        if "rewrite_links" not in names:
            names.append("rewrite_links")
    return names
