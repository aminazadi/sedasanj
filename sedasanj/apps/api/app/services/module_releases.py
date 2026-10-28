"""Signed FreePBX module releases: zip checks, signing, changelog sanitising, update choice."""

from __future__ import annotations

import base64
import hashlib
import re
import stat
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from typing import Protocol
from xml.etree import ElementTree

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.config import get_settings
from app.errors import ApiError

PRODUCT_FREEPBX = "freepbx-recuploader"
MODULE_RAWNAME = "recuploader"
SEVERITIES = ("normal", "recommended", "critical", "security")
CHANNELS = ("stable", "beta")

_VERSION_RE = re.compile(r"^(\d{1,4})\.(\d{1,4})\.(\d{1,4})$")
_MAX_ZIP_ENTRIES = 5000
_MAX_UNCOMPRESSED_BYTES = 1024 * 1024 * 1024


def parse_version(value: str) -> tuple[int, int, int]:
    match = _VERSION_RE.match(value.strip())
    if match is None:
        raise ApiError("invalid_request", f"version must look like 1.2.3, got {value!r}")
    major, minor, patch = (int(part) for part in match.groups())
    return major, minor, patch


def try_parse_version(value: str | None) -> tuple[int, int, int] | None:
    try:
        return parse_version(value or "")
    except ApiError:
        return None


@dataclass(frozen=True)
class ZipInspection:
    rawname: str
    version: str
    sha256: str
    size: int


def inspect_zip(path: Path) -> ZipInspection:
    """Validate a module zip the same way the on-host updater will, before it is ever stored."""
    size = path.stat().st_size
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise ApiError("unsupported_archive", "file is not a valid zip archive") from exc
    with archive:
        entries = archive.infolist()
        if not entries or len(entries) > _MAX_ZIP_ENTRIES:
            raise ApiError("archive_unsafe", "zip has no entries or too many entries")
        total = 0
        prefix = f"{MODULE_RAWNAME}/"
        for entry in entries:
            name = entry.filename
            parts = name.split("/")
            if name.startswith("/") or "\\" in name or ".." in parts or ":" in parts[0]:
                raise ApiError("archive_unsafe", f"unsafe path in zip: {name}")
            if not name.startswith(prefix):
                raise ApiError("archive_unsafe", f"every entry must live under {prefix}: {name}")
            if stat.S_ISLNK(entry.external_attr >> 16):
                raise ApiError("archive_unsafe", f"symlinks are not allowed: {name}")
            total += entry.file_size
        if total > _MAX_UNCOMPRESSED_BYTES:
            raise ApiError("archive_too_large", "zip expands beyond the allowed size")
        try:
            module_xml = archive.read(f"{prefix}module.xml")
        except KeyError as exc:
            raise ApiError("invalid_request", f"zip has no {prefix}module.xml") from exc
    try:
        root = ElementTree.fromstring(module_xml)
    except ElementTree.ParseError as exc:
        raise ApiError("invalid_request", "module.xml is not valid XML") from exc
    rawname = (root.findtext("rawname") or "").strip()
    version = (root.findtext("version") or "").strip()
    if rawname != MODULE_RAWNAME:
        raise ApiError("invalid_request", f"module.xml rawname must be {MODULE_RAWNAME}")
    parse_version(version)
    return ZipInspection(rawname=rawname, version=version, sha256=digest.hexdigest(), size=size)


def _signing_key() -> Ed25519PrivateKey:
    raw = get_settings().module_release_signing_key
    if not raw:
        raise ApiError("internal", "MODULE_RELEASE_SIGNING_KEY is not configured")
    try:
        seed = base64.b64decode(raw, validate=True)
        return Ed25519PrivateKey.from_private_bytes(seed)
    except ValueError as exc:
        raise ApiError(
            "internal", "MODULE_RELEASE_SIGNING_KEY must be a base64 32-byte seed"
        ) from exc


def sign_digest(sha256_hex: str) -> str:
    """Detached Ed25519 signature over the ASCII sha256 hex digest, base64-encoded."""
    return base64.b64encode(_signing_key().sign(sha256_hex.encode("ascii"))).decode("ascii")


def public_key_b64() -> str:
    raw = (
        _signing_key()
        .public_key()
        .public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    )
    return base64.b64encode(raw).decode("ascii")


def artifact_key(product: str, version: str) -> str:
    return f"module-releases/{product}/{version}.zip"


# --- changelog sanitising -------------------------------------------------

_ALLOWED_TAGS: dict[str, frozenset[str]] = {
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
    "table": frozenset(),
    "thead": frozenset(),
    "tbody": frozenset(),
    "tr": frozenset(),
    "th": frozenset({"colspan", "rowspan"}),
    "td": frozenset({"colspan", "rowspan"}),
}
_VOID_TAGS = frozenset({"br", "hr"})
_DROP_CONTENT_TAGS = frozenset(
    {"script", "style", "iframe", "object", "embed", "template", "noscript"}
)
_SAFE_HREF = re.compile(r"^(https?://|mailto:|#)", re.IGNORECASE)
_SAFE_CLASS = re.compile(r"^language-[a-z0-9+#-]{1,32}$")
_SAFE_SPAN = re.compile(r"^\d{1,2}$")


class _Sanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.text: list[str] = []
        self.stack: list[str] = []
        self.dropping = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _DROP_CONTENT_TAGS:
            self.dropping += 1
            return
        if self.dropping or tag not in _ALLOWED_TAGS:
            return
        kept: list[str] = []
        for name, value in attrs:
            if name not in _ALLOWED_TAGS[tag] or value is None:
                continue
            value = value.strip()
            if name == "href" and not _SAFE_HREF.match(value):
                continue
            if name == "class" and not _SAFE_CLASS.match(value):
                continue
            if name in ("colspan", "rowspan") and not _SAFE_SPAN.match(value):
                continue
            kept.append(f' {name}="{escape(value, quote=True)}"')
        if tag == "a":
            kept.append(' rel="noopener noreferrer" target="_blank"')
        self.out.append(f"<{tag}{''.join(kept)}>")
        if tag not in _VOID_TAGS:
            self.stack.append(tag)
        if tag in ("br", "p", "li", "h2", "h3", "h4", "tr"):
            self.text.append("\n")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _VOID_TAGS:
            self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag in _DROP_CONTENT_TAGS:
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


def sanitize_changelog(html: str) -> tuple[str, str]:
    """Allowlist-rebuild the TinyMCE HTML; returns (safe_html, plain_text)."""
    parser = _Sanitizer()
    parser.feed(html)
    return parser.finish()


# --- update selection -----------------------------------------------------


class ReleaseLike(Protocol):
    version: str
    version_major: int
    version_minor: int
    version_patch: int
    status: str
    channel: str
    min_freepbx_major: int | None
    min_from_version: str | None


def _key(release: ReleaseLike) -> tuple[int, int, int]:
    return release.version_major, release.version_minor, release.version_patch


def freepbx_major(value: str | None) -> int | None:
    match = re.match(r"^\s*(\d+)", value or "")
    return int(match.group(1)) if match else None


def select_update[R: ReleaseLike](
    releases: Sequence[R],
    current: str,
    *,
    freepbx: str | None = None,
    channel: str = "stable",
) -> tuple[R | None, list[R]]:
    """Pick the newest installable release above `current` and every release in between.

    The changelog list is newest first so the host can show everything it is about to gain.
    """
    current_key = try_parse_version(current) or (0, 0, 0)
    host_major = freepbx_major(freepbx)
    allowed_channels = {"stable"} if channel == "stable" else set(CHANNELS)
    newer = sorted(
        (
            release
            for release in releases
            if release.status == "published"
            and release.channel in allowed_channels
            and _key(release) > current_key
        ),
        key=_key,
        reverse=True,
    )
    latest: R | None = None
    for release in newer:
        if release.min_freepbx_major and host_major and host_major < release.min_freepbx_major:
            continue
        floor = try_parse_version(release.min_from_version)
        if floor and current_key < floor:
            continue
        latest = release
        break
    if latest is None:
        return None, []
    return latest, [release for release in newer if _key(release) <= _key(latest)]
