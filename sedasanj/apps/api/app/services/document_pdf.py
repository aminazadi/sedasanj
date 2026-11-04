"""Render private A4 documents in memory using the bundled Persian font."""

from __future__ import annotations

import io
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote
from uuid import UUID

from fastapi.responses import Response
from markdown_it import MarkdownIt
from markdown_it.tree import SyntaxTreeNode
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen.canvas import Canvas
from starlette.concurrency import run_in_threadpool

from app.errors import ApiError
from app.services.call_export import CALL_TYPE_LABELS, to_jalali
from app.services.pdf_text import FONT, PDF_RENDER_LOCK, register_font, visual_text, wrap_rtl

logger = logging.getLogger(__name__)
GREEN = HexColor("#4B6E48")
INK = HexColor("#263226")
MUTED = HexColor("#5B655A")
LINE = HexColor("#CBD5C7")
PALE = HexColor("#F2F5F0")
DIGITS = str.maketrans("0123456789.,", "۰۱۲۳۴۵۶۷۸۹٫٬")
TITLE_LINE = re.compile(r"^#[ \t]+(.+?)[ \t]*#*$")
MARKDOWN = MarkdownIt("commonmark", {"html": False}).enable("table")


@dataclass(frozen=True)
class Document:
    title: str
    kind: str
    metadata: Sequence[tuple[str, str]]
    markdown: str
    charts: Sequence[dict[str, Any]] = ()


def number(value: int | float) -> str:
    return f"{value:,}".translate(DIGITS)


def without_title(markdown: str, title: str) -> str:
    first, _, body = markdown.strip().partition("\n")
    heading = TITLE_LINE.fullmatch(first.strip())
    if heading and heading[1].strip() == title.strip():
        return body.lstrip()
    return markdown


def chart_label(label: str) -> str:
    if len(label) == 10:
        try:
            date = datetime.fromisoformat(label).replace(tzinfo=UTC, hour=12)
        except ValueError:
            pass
        else:
            return to_jalali(date).split()[0].translate(DIGITS)
    return CALL_TYPE_LABELS.get(label, label)


def _plain(node: SyntaxTreeNode) -> str:
    if node.type in {"text", "code_inline", "fence", "code_block"}:
        return node.content
    if node.type in {"softbreak", "hardbreak"}:
        return "\n"
    return "".join(_plain(child) for child in node.children)


class _Layout:
    margin = 47
    bottom = 53
    leading = 17
    width, height = A4
    right = width - margin
    body_width = width - 2 * margin

    def __init__(self, canvas: Canvas, kind: str) -> None:
        self.canvas = canvas
        self.kind = kind
        self.y = 0.0
        self.new_page()

    def new_page(self) -> None:
        canvas = self.canvas
        if self.y:
            canvas.showPage()
        canvas.setFillColor(GREEN)
        canvas.rect(self.margin, self.height - 42, 6, 6, stroke=0, fill=1)
        canvas.rect(self.margin + 9, self.height - 42, 6, 6, stroke=0, fill=1)
        canvas.rect(self.margin, self.height - 33, 6, 6, stroke=0, fill=1)
        canvas.setFont(FONT, 10)
        canvas.drawRightString(self.right, self.height - 41, visual_text("صداسنج  |  " + self.kind))
        canvas.setStrokeColor(GREEN)
        canvas.line(self.margin, self.height - 50, self.right, self.height - 50)
        canvas.setStrokeColor(LINE)
        canvas.line(self.margin, 39, self.right, 39)
        canvas.setFillColor(MUTED)
        canvas.drawRightString(self.right, 25, visual_text(self.kind))
        canvas.drawString(self.margin, 25, visual_text("صفحه " + number(canvas.getPageNumber())))
        self.y = self.height - 75

    def ensure(self, height: float) -> None:
        if self.y - height < self.bottom:
            self.new_page()

    def paragraph(
        self,
        text: str,
        *,
        size: float = 10.5,
        heading: bool = False,
        indent: int = 0,
    ) -> None:
        if not text.strip():
            return
        leading = max(self.leading, size * 1.6)
        if heading:
            self.ensure(leading + 32)
        for line in wrap_rtl(text, size, self.body_width - indent):
            self.ensure(leading)
            self.canvas.setFont(FONT, size)
            self.canvas.setFillColor(GREEN if heading else INK)
            self.canvas.drawRightString(self.right - indent, self.y - size, line)
            self.y -= leading
        self.y -= 6

    def rule(self) -> None:
        self.ensure(13)
        self.canvas.setStrokeColor(LINE)
        self.canvas.line(self.margin, self.y - 3, self.right, self.y - 3)
        self.y -= 13

    def table(
        self,
        header: Sequence[str],
        rows: Sequence[Sequence[str]],
        *,
        bars: Sequence[float] = (),
    ) -> None:
        if not header:
            return
        if len(header) > 6:
            for start in range(0, len(header), 6):
                end = start + 6
                self.table(header[start:end], [row[start:end] for row in rows])
            return
        cell_width = self.body_width / len(header)
        size = 9
        leading = 15
        max_lines = int((self.height - 155 - self.bottom) / leading)

        def wrap(row: Sequence[str]) -> list[list[str]]:
            return [wrap_rtl(cell, size, cell_width - 14) for cell in row]

        def draw(cells: list[list[str]], line_count: int, *, label: bool, shade: bool) -> None:
            height = line_count * leading + 8
            if label or shade:
                self.canvas.setFillColor(LINE if label else PALE)
                self.canvas.rect(
                    self.margin, self.y - height, self.body_width, height, stroke=0, fill=1
                )
            self.canvas.setFont(FONT, size)
            self.canvas.setFillColor(INK)
            for column, lines in enumerate(cells):
                for offset, line in enumerate(lines):
                    self.canvas.drawRightString(
                        self.right - column * cell_width - 7,
                        self.y - 6 - size - offset * leading,
                        line,
                    )
            self.y -= height

        headings = wrap(header)
        # Keep unusually large Markdown table headers from consuming an entire page.
        headings = [lines[:4] for lines in headings]
        header_lines = max(map(len, headings))
        header_height = header_lines * leading + 8
        self.ensure(header_height + leading + 8)
        draw(headings, header_lines, label=True, shade=False)
        for index, row in enumerate(rows):
            cells = wrap(row)
            for offset in range(0, max(map(len, cells)), max_lines):
                chunk = [lines[offset : offset + max_lines] for lines in cells]
                count = max(map(len, chunk))
                if self.y - (count * leading + 8) < self.bottom:
                    self.new_page()
                    draw(headings, header_lines, label=True, shade=False)
                draw(chunk, count, label=False, shade=index % 2 == 0)
                if bars and offset == 0:
                    bar_width = cell_width - 14
                    left = self.margin + 7
                    y = self.y + (count * leading + 8) / 2 - 2.5
                    self.canvas.setFillColor(LINE)
                    self.canvas.rect(left, y, bar_width, 5, stroke=0, fill=1)
                    filled = bars[index] * bar_width
                    self.canvas.setFillColor(GREEN)
                    self.canvas.rect(left + bar_width - filled, y, filled, 5, stroke=0, fill=1)
        self.y -= 12

    def markdown(self, node: SyntaxTreeNode, *, indent: int = 0) -> None:
        if node.type in {"heading", "paragraph", "fence", "code_block"}:
            heading = node.type == "heading"
            self.paragraph(
                _plain(node), size=13 if heading else 10.5, heading=heading, indent=indent
            )
        elif node.type == "hr":
            self.rule()
        elif node.type == "table":
            groups = [
                [[_plain(cell) for cell in row.children] for row in group.children]
                for group in node.children
            ]
            if groups and groups[0]:
                self.table(groups[0][0], [row for group in groups[1:] for row in group])
        elif node.type in {"bullet_list", "ordered_list"}:
            start = int(node.attrs.get("start", 1))
            for index, item in enumerate(node.children, start):
                if item.children and item.children[0].type == "paragraph":
                    prefix = number(index) + ") " if node.type == "ordered_list" else "• "
                    self.paragraph(prefix + _plain(item.children[0]), indent=indent + 9)
                    for child in item.children[1:]:
                        self.markdown(child, indent=indent + 9)
                else:
                    self.markdown(item, indent=indent + 9)
        else:
            for child in node.children:
                self.markdown(child, indent=indent)

    def chart(self, chart: dict[str, Any]) -> None:
        data = chart["data"]
        if not data:
            return
        self.paragraph(chart["title"], size=13, heading=True)
        columns = ["شاخص", chart["value_label"]]
        secondary = chart.get("secondary_value_label")
        if secondary:
            columns.append(secondary)
        rows = [
            [chart_label(item["label"]), number(item["value"])]
            + (
                [number(item["secondary_value"]) if "secondary_value" in item else "—"]
                if secondary
                else []
            )
            for item in data
        ]
        peak = max((item["value"] for item in data), default=0)
        bars = [max(item["value"], 0) / peak for item in data] if peak > 0 else []
        if bars:
            columns.append("مقایسه")
            for row in rows:
                row.append("")
        self.table(columns, rows, bars=bars)


def render(document: Document) -> bytes:
    with PDF_RENDER_LOCK:
        register_font()
        output = io.BytesIO()
        canvas = Canvas(output, pagesize=A4, pageCompression=1)
        canvas.setTitle(document.title)
        canvas.setAuthor("صداسنج")
        page = _Layout(canvas, document.kind)
        page.paragraph(document.title, size=22, heading=True)
        for label, value in document.metadata:
            page.paragraph(f"{label}  {value}", size=10)
        page.rule()
        page.markdown(
            SyntaxTreeNode(MARKDOWN.parse(without_title(document.markdown, document.title)))
        )
        if document.charts:
            page.paragraph("آمار گزارش", size=15, heading=True)
            for chart in document.charts:
                page.chart(chart)
        canvas.save()
        return output.getvalue()


async def download(document: Document, kind: str, document_id: UUID) -> Response:
    try:
        content = await run_in_threadpool(render, document)
    except Exception:
        logger.warning("document_pdf_render_failed kind=%s id=%s", kind, document_id)
        raise ApiError(
            "document_pdf_unavailable",
            "آماده‌سازی PDF با خطا روبه‌رو شد؛ دوباره تلاش کنید یا گزینه چاپ را بزنید.",
        ) from None
    name = quote(document.title[:80] + ".pdf", safe="")
    return Response(
        content,
        media_type="application/pdf",
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": (
                f"attachment; filename=\"{kind}-{document_id}.pdf\"; filename*=UTF-8''{name}"
            ),
        },
    )
