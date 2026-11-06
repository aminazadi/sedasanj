from __future__ import annotations

import re
from functools import cache
from pathlib import Path
from threading import Lock
from typing import Any

import arabic_reshaper
from bidi.algorithm import get_display
from reportlab.lib.colors import HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import FILL_EVEN_ODD

FONT = "SedaSanjVazirmatn"
PDF_RENDER_LOCK = Lock()
BIDI_ISOLATES = str.maketrans("", "", "\u2066\u2067\u2068\u2069")


@cache
def register_font() -> None:
    path = Path(__file__).resolve().parents[1] / "assets/fonts/Vazirmatn-Regular.ttf"
    pdfmetrics.registerFont(TTFont(FONT, str(path)))


def visual_text(text: str) -> str:
    return str(get_display(arabic_reshaper.reshape(text.translate(BIDI_ISOLATES)), base_dir="R"))


def wrap_rtl(text: str, size: float, width: float) -> list[str]:
    """Wrap in logical order and apply shaping and bidi ordering to each line."""
    lines: list[str] = []
    for part in text.splitlines() or [""]:
        current = ""
        for token in re.findall(r"\S+\s*", part):
            if pdfmetrics.stringWidth(visual_text(current + token), FONT, size) <= width:
                current += token
                continue
            if current:
                lines.append(visual_text(current.rstrip()))
                current = ""
            if pdfmetrics.stringWidth(visual_text(token), FONT, size) <= width:
                current = token
                continue
            for char in token:
                if current and (
                    pdfmetrics.stringWidth(visual_text(current + char), FONT, size) > width
                ):
                    lines.append(visual_text(current))
                    current = ""
                current += char
        lines.append(visual_text(current.rstrip()))
    return lines


SITE_URL = "sedasanj.ir"
LOGO_PATH = Path(__file__).resolve().parents[1] / "assets/sedasanj-logo.svg"


@cache
def _logo_contours() -> tuple[tuple[tuple[str, tuple[float, ...]], ...], tuple[float, ...]]:
    """Parse the M/C/Z-only logo path and return (commands, (min_x, min_y, max_x, max_y))."""
    source = LOGO_PATH.read_text(encoding="utf-8")
    match = re.search(r'<path[^>]+\sd="([^"]+)"', source)
    if not match:
        raise ValueError("logo path missing")
    commands: list[tuple[str, tuple[float, ...]]] = []
    for command, args in re.findall(r"([MCZ])([^MCZ]*)", match[1]):
        commands.append((command, tuple(float(n) for n in re.findall(r"-?\d+(?:\.\d+)?", args))))
    xs = [v for _, a in commands for v in a[0::2]]
    ys = [v for _, a in commands for v in a[1::2]]
    return tuple(commands), (min(xs), min(ys), max(xs), max(ys))


def logo_width(height: float) -> float:
    _, (min_x, min_y, max_x, max_y) = _logo_contours()
    return (max_x - min_x) * height / (max_y - min_y)


def draw_logo(canvas: Any, x: float, y: float, height: float, color: str = "#4B6E48") -> float:
    """Draw the logo with its bottom-left at (x, y); return the drawn width."""
    commands, (min_x, min_y, max_x, max_y) = _logo_contours()
    scale = height / (max_y - min_y)
    path = canvas.beginPath()

    def point(px: float, py: float) -> tuple[float, float]:
        return x + (px - min_x) * scale, y + (max_y - py) * scale

    for command, a in commands:
        if command == "M":
            path.moveTo(*point(a[0], a[1]))
        elif command == "C":
            path.curveTo(*point(a[0], a[1]), *point(a[2], a[3]), *point(a[4], a[5]))
        else:
            path.close()
    canvas.saveState()
    canvas.setFillColor(HexColor(color))
    canvas.drawPath(path, stroke=0, fill=1, fillMode=FILL_EVEN_ODD)
    canvas.restoreState()
    return (max_x - min_x) * scale


def draw_site_footer(canvas: Any, center_x: float, baseline: float, color: str = "#5B655A") -> None:
    """Centered logo + site address, sized for a small page footer (logo ~11pt high)."""
    size, gap, logo_height = 8.5, 6.0, 11.0
    text_width = pdfmetrics.stringWidth(SITE_URL, "Helvetica", size)
    width = logo_width(logo_height)
    left = center_x - (width + gap + text_width) / 2
    draw_logo(canvas, left, baseline - 2.5, logo_height)
    canvas.saveState()
    canvas.setFillColor(HexColor(color))
    canvas.setFont("Helvetica", size)
    canvas.drawString(left + width + gap, baseline, SITE_URL)
    canvas.restoreState()
