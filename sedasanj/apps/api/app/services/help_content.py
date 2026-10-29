"""Help-center content rules: HTML sanitising, media validation and the module error catalog.

Article bodies are written by staff in a rich-text editor and rendered on public pages, so they
are rebuilt from an allowlist on every write (never trusted from the editor). Images and videos
may only point at media uploaded to this platform (`/v1/help/media/<uuid>`) or, for embeds, at a
small set of privacy-friendly video hosts with a fixed sandbox.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
ERROR_CODE_RE = re.compile(r"^[A-Za-z0-9_.-]{2,40}$")

MEDIA_URL = re.compile(
    r"^/v1/help/media/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
SAFE_HREF = re.compile(r"^(https?://|mailto:|#|/help/)", re.IGNORECASE)
SAFE_CLASS = re.compile(r"^language-[a-z0-9+#-]{1,32}$")
SAFE_NUMBER = re.compile(r"^\d{1,4}$")
EMBED_URLS = (
    re.compile(
        r"^https://www\.youtube-nocookie\.com/embed/[A-Za-z0-9_-]{6,20}(\?[A-Za-z0-9=&_-]*)?$"
    ),
    re.compile(
        r"^https://www\.aparat\.com/video/video/embed/videohash/[A-Za-z0-9]{3,20}/vt/frame$"
    ),
)

_ALLOWED: dict[str, frozenset[str]] = {
    "p": frozenset(),
    "br": frozenset(),
    "hr": frozenset(),
    "h2": frozenset(),
    "h3": frozenset(),
    "h4": frozenset(),
    "strong": frozenset(),
    "b": frozenset(),
    "em": frozenset(),
    "i": frozenset(),
    "u": frozenset(),
    "s": frozenset(),
    "mark": frozenset(),
    "span": frozenset(),
    "ul": frozenset(),
    "ol": frozenset(),
    "li": frozenset(),
    "blockquote": frozenset(),
    "code": frozenset({"class"}),
    "pre": frozenset({"class"}),
    "a": frozenset({"href", "title"}),
    "img": frozenset({"src", "alt", "width", "height"}),
    "figure": frozenset(),
    "figcaption": frozenset(),
    "video": frozenset({"src", "poster", "controls", "width", "height", "preload"}),
    "iframe": frozenset({"src", "title", "width", "height"}),
    "table": frozenset(),
    "thead": frozenset(),
    "tbody": frozenset(),
    "tr": frozenset(),
    "th": frozenset({"colspan", "rowspan"}),
    "td": frozenset({"colspan", "rowspan"}),
}
_VOID = frozenset({"br", "hr", "img"})
_DROP_CONTENT = frozenset({"script", "style", "object", "embed", "template", "noscript", "svg"})
_BLOCK_TEXT = frozenset({"br", "p", "li", "h2", "h3", "h4", "tr", "figcaption"})


class _Sanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.text: list[str] = []
        self.stack: list[str] = []
        self.dropping = 0

    def _attributes(self, tag: str, attrs: list[tuple[str, str | None]]) -> str | None:
        """Returns the rebuilt attribute string, or None when the element must be dropped."""
        kept: list[str] = []
        present: dict[str, str] = {}
        for name, value in attrs:
            if name not in _ALLOWED[tag]:
                continue
            if name == "controls":
                present[name] = ""
                continue
            if value is None:
                continue
            value = value.strip()
            if name == "href" and not SAFE_HREF.match(value):
                continue
            if name == "class" and not SAFE_CLASS.match(value):
                continue
            if name in ("colspan", "rowspan", "width", "height") and not SAFE_NUMBER.match(value):
                continue
            if name == "preload" and value not in ("none", "metadata"):
                continue
            if name in ("src", "poster"):
                if tag == "iframe":
                    if not any(pattern.match(value) for pattern in EMBED_URLS):
                        return None
                elif not MEDIA_URL.match(value):
                    return None
            present[name] = value
        for name, value in present.items():
            kept.append(
                f" {name}" if name == "controls" else f' {name}="{escape(value, quote=True)}"'
            )
        if tag in ("img", "video") and "src" not in present:
            return None
        if tag == "iframe":
            if "src" not in present:
                return None
            kept.append(
                ' sandbox="allow-scripts allow-same-origin allow-presentation"'
                ' allow="fullscreen" allowfullscreen loading="lazy" referrerpolicy="no-referrer"'
            )
        if tag == "video" and "controls" not in present:
            kept.append(" controls")
        if tag == "img":
            kept.append(' loading="lazy"')
        if tag == "a":
            kept.append(' rel="noopener noreferrer" target="_blank"')
        return "".join(kept)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _DROP_CONTENT:
            self.dropping += 1
            return
        if self.dropping or tag not in _ALLOWED:
            return
        rebuilt = self._attributes(tag, attrs)
        if rebuilt is None:
            return
        self.out.append(f"<{tag}{rebuilt}>")
        if tag not in _VOID:
            self.stack.append(tag)
        if tag in _BLOCK_TEXT:
            self.text.append("\n")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _VOID:
            self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag in _DROP_CONTENT:
            self.dropping = max(0, self.dropping - 1)
            return
        if self.dropping or tag not in self.stack:
            return
        while self.stack:
            open_tag = self.stack.pop()
            self.out.append(f"</{open_tag}>")
            if open_tag == tag:
                break

    def handle_data(self, data: str) -> None:
        if self.dropping:
            return
        self.out.append(escape(data, quote=False))
        self.text.append(data)

    def finish(self) -> tuple[str, str]:
        self.close()
        while self.stack:
            self.out.append(f"</{self.stack.pop()}>")
        plain = re.sub(r"\n{3,}", "\n\n", "".join(self.text)).strip()
        return "".join(self.out).strip(), plain


def sanitize_help_html(html: str) -> tuple[str, str]:
    """Allowlist-rebuild editor HTML; returns (safe_html, plain_text for search)."""
    parser = _Sanitizer()
    parser.feed(html)
    return parser.finish()


# --- media ------------------------------------------------------------------

IMAGE_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
VIDEO_TYPES = {"video/mp4": ".mp4", "video/webm": ".webm"}
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_VIDEO_BYTES = 120 * 1024 * 1024


def sniff_media(head: bytes) -> tuple[str, str] | None:
    """Detect the real type from magic bytes: returns (kind, content_type) or None.

    The declared Content-Type of an upload is never trusted; SVG and anything unknown is refused.
    """
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image", "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image", "image/jpeg"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image", "image/webp"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "image", "image/gif"
    if len(head) >= 12 and head[4:8] == b"ftyp":
        return "video", "video/mp4"
    if head.startswith(b"\x1a\x45\xdf\xa3"):
        return "video", "video/webm"
    return None


def media_limit(kind: str) -> int:
    return MAX_IMAGE_BYTES if kind == "image" else MAX_VIDEO_BYTES


def media_extension(content_type: str) -> str:
    return {**IMAGE_TYPES, **VIDEO_TYPES}[content_type]


# --- module error catalog ----------------------------------------------------

CATALOG_PATH = Path(__file__).resolve().parents[1] / "data" / "module_error_codes.json"


@lru_cache(maxsize=1)
def module_error_catalog() -> list[dict[str, Any]]:
    """Error codes defined by the FreePBX module (exported from its ErrorCatalog.php)."""
    return list(json.loads(CATALOG_PATH.read_text(encoding="utf-8")))
