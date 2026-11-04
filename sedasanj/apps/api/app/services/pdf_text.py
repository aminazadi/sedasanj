from __future__ import annotations

import re
from functools import cache
from pathlib import Path
from threading import Lock

import arabic_reshaper
from bidi.algorithm import get_display
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

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
