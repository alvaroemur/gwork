from __future__ import annotations

"""Conversión entre tokens del manifiesto y tipos de la Docs API."""

import re
from typing import Any, Optional


def hex_to_rgb(hex_str: str) -> dict:
    """#RRGGBB o #RGB → RgbColor de la Docs API (componentes 0.0–1.0)."""
    clean = str(hex_str).strip().lstrip("#")
    if len(clean) == 3:
        clean = "".join(c * 2 for c in clean)
    if len(clean) != 6:
        return {"red": 0.0, "green": 0.0, "blue": 0.0}
    return {
        "red": round(int(clean[0:2], 16) / 255.0, 4),
        "green": round(int(clean[2:4], 16) / 255.0, 4),
        "blue": round(int(clean[4:6], 16) / 255.0, 4),
    }


def rgb_to_hex(rgb: Optional[dict]) -> str:
    """RgbColor de la Docs API → #RRGGBB."""
    if not rgb:
        return "#000000"
    r = int(round(rgb.get("red", 0.0) * 255))
    g = int(round(rgb.get("green", 0.0) * 255))
    b = int(round(rgb.get("blue", 0.0) * 255))
    return f"#{r:02X}{g:02X}{b:02X}"


def parse_pt(value: Any) -> float:
    """Extrae puntos de un número o una cadena tipo '35pt'."""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip().lower().replace("pt", ""))
    except ValueError:
        return 0.0


def parse_border(border_val: Any) -> tuple:
    """'1.25pt solid #E6007E' → (ancho_pt, dashStyle, color_hex)."""
    if not border_val:
        return 1.0, "SOLID", "#000000"
    val = str(border_val).strip()

    width = 1.0
    m = re.search(r"([\d.]+)\s*(?:pt)?", val)
    if m:
        try:
            width = float(m.group(1))
        except ValueError:
            width = 1.0

    lowered = val.lower()
    dash_style = "DASH" if "dash" in lowered else ("DOT" if "dot" in lowered else "SOLID")

    color = "#000000"
    m = re.search(r"#[0-9a-fA-F]{3,6}", val)
    if m:
        color = m.group(0)

    return width, dash_style, color


def colors_match(hex_a: str, rgb_b: Optional[dict], tol: float = 0.05) -> bool:
    """Compara un hex del manifiesto contra un RgbColor vivo, con tolerancia."""
    if not rgb_b:
        return False
    a = hex_to_rgb(hex_a)
    return (
        abs(a["red"] - rgb_b.get("red", 0.0)) <= tol
        and abs(a["green"] - rgb_b.get("green", 0.0)) <= tol
        and abs(a["blue"] - rgb_b.get("blue", 0.0)) <= tol
    )


def is_bold_weight(weight: Any, threshold: int = 700) -> bool:
    """La Docs API solo tiene bold binario; los pesos >= 700 se mapean a bold."""
    try:
        return int(weight) >= threshold
    except (TypeError, ValueError):
        return False
