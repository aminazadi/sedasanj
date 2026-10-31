"""Signed FreePBX module releases: zip checks, signing, changelog sanitising, update choice."""

from __future__ import annotations

import base64
import fcntl
import hashlib
import io
import json
import os
import re
import stat
import tarfile
import tempfile
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
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
PRODUCT_ISSABEL = "issabel-recuploader"
PRODUCTS = (PRODUCT_FREEPBX, PRODUCT_ISSABEL)
MODULE_RAWNAME = "recuploader"
SEVERITIES = ("normal", "recommended", "critical", "security")
CHANNELS = ("stable", "beta")

_VERSION_RE = re.compile(r"^(\d{1,4})\.(\d{1,4})\.(\d{1,4})$")
_MAX_ZIP_ENTRIES = 5000
_MAX_UNCOMPRESSED_BYTES = 1024 * 1024 * 1024
_PUBLIC_KEY_ENTRY = f"{MODULE_RAWNAME}/assets/release-signing.pub"


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
    product: str = PRODUCT_FREEPBX
    archive_format: str = "zip"


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
        seen: set[str] = set()
        prefix = f"{MODULE_RAWNAME}/"
        for entry in entries:
            name = entry.filename
            parts = name.split("/")
            if name in seen:
                raise ApiError("archive_unsafe", "duplicate module archive entry")
            seen.add(name)
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


def inspect_artifact(path: Path) -> ZipInspection:
    if zipfile.is_zipfile(path):
        result = inspect_zip(path)
        with zipfile.ZipFile(path) as archive:
            root = ElementTree.fromstring(archive.read(f"{MODULE_RAWNAME}/module.xml"))
        if root.findtext("product") not in (None, PRODUCT_FREEPBX):
            raise ApiError("invalid_request", "Issabel packages must use tgz")
        return result
    total = 0
    names: set[str] = set()
    xml: bytes | None = None
    try:
        with tarfile.open(path, "r:gz") as archive:
            for entry in archive:
                parts = entry.name.rstrip("/").split("/")
                if (
                    len(names) >= _MAX_ZIP_ENTRIES
                    or entry.name in names
                    or parts[0] != MODULE_RAWNAME
                    or any(part in ("", ".", "..") for part in parts)
                    or "\\" in entry.name
                    or any(ord(char) < 32 for char in entry.name)
                    or not (entry.isfile() or entry.isdir())
                    or entry.mode & 0o7000
                ):
                    raise ApiError("archive_unsafe", "unsafe or duplicate entry in module tgz")
                names.add(entry.name)
                total += entry.size
                if total > _MAX_UNCOMPRESSED_BYTES:
                    raise ApiError("archive_too_large", "module expands beyond the allowed size")
                if entry.name == f"{MODULE_RAWNAME}/module.xml":
                    if entry.size > 65536:
                        raise ApiError("archive_unsafe", "module.xml is too large")
                    handle = archive.extractfile(entry)
                    xml = handle.read() if handle else None
        if xml is None:
            raise ApiError("invalid_request", "tgz has no recuploader/module.xml")
        root = ElementTree.fromstring(xml)
    except (tarfile.TarError, OSError, EOFError, ElementTree.ParseError) as exc:
        raise ApiError("unsupported_archive", "invalid module tgz") from exc
    if root.findtext("rawname") != MODULE_RAWNAME or root.findtext("product") != PRODUCT_ISSABEL:
        raise ApiError("invalid_request", "tgz must identify the issabel-recuploader product")
    version = root.findtext("version") or ""
    parse_version(version)
    with path.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    return ZipInspection(
        MODULE_RAWNAME, version, digest, path.stat().st_size, PRODUCT_ISSABEL, "tgz"
    )


def validate_product(product: str) -> str:
    if product not in PRODUCTS:
        raise ApiError("invalid_request", "unknown module product")
    return product


def _signing_key() -> Ed25519PrivateKey:
    raw = get_settings().module_release_signing_key
    if raw:
        try:
            seed = base64.b64decode(raw, validate=True)
            return Ed25519PrivateKey.from_private_bytes(seed)
        except ValueError as exc:
            raise ApiError(
                "internal", "MODULE_RELEASE_SIGNING_KEY must be a base64 32-byte seed"
            ) from exc

    configured_path = get_settings().module_release_signing_key_file
    if not configured_path:
        raise ApiError("internal", "MODULE_RELEASE_SIGNING_KEY is not configured")
    path = Path(configured_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f".{path.name}.lock")
    with lock_path.open("a+b") as lock:
        os.chmod(lock_path, 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            seed = path.read_bytes()
        except FileNotFoundError:
            seed = Ed25519PrivateKey.generate().private_bytes(
                serialization.Encoding.Raw,
                serialization.PrivateFormat.Raw,
                serialization.NoEncryption(),
            )
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
            )
            temporary = Path(temporary_name)
            try:
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(seed)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, path)
            finally:
                temporary.unlink(missing_ok=True)
            os.chmod(path, 0o600)
    try:
        return Ed25519PrivateKey.from_private_bytes(seed)
    except ValueError as exc:
        raise ApiError(
            "internal", "MODULE_RELEASE_SIGNING_KEY_FILE must contain a raw 32-byte seed"
        ) from exc


def sign_digest(sha256_hex: str) -> str:
    """Detached Ed25519 signature over the ASCII sha256 hex digest, base64-encoded."""
    return base64.b64encode(_signing_key().sign(sha256_hex.encode("ascii"))).decode("ascii")


class ManifestSource(Protocol):
    product: str
    version: str
    artifact_sha256: str
    artifact_size: int
    channel: str
    min_freepbx_major: int | None
    min_from_version: str | None


MANIFEST_DOMAIN = b"sedasanj-module-manifest-v1\n"
MANIFEST_TTL = timedelta(days=7)


def build_manifest(release: ManifestSource, *, now: datetime | None = None) -> str:
    """Canonical JSON describing exactly what a host may install.

    The zip signature only proves "this file was published once"; the manifest binds the version,
    digest, size, channel and compatibility floor, and expires, so an old signed zip cannot be
    replayed as a new release and a captured offer stops working after a week.
    """
    issued = (now or datetime.now(UTC)).replace(microsecond=0)
    payload = {
        "product": release.product,
        "rawname": MODULE_RAWNAME,
        "version": release.version,
        "sha256": release.artifact_sha256,
        "size": int(release.artifact_size),
        "channel": release.channel,
        "min_freepbx_major": release.min_freepbx_major,
        "min_from_version": release.min_from_version,
        "issued_at": issued.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expires_at": (issued + MANIFEST_TTL).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if release.product == PRODUCT_ISSABEL:
        payload.update(
            {
                "archive_format": "tgz",
                "min_issabel_major": getattr(release, "min_issabel_major", None),
                "max_issabel_major": getattr(release, "max_issabel_major", None),
                "min_php_version": getattr(release, "min_php_version", None),
            }
        )
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sign_manifest(manifest: str) -> str:
    """Sign a domain-separated manifest independently of artifact digests."""
    return base64.b64encode(_signing_key().sign(MANIFEST_DOMAIN + manifest.encode("ascii"))).decode(
        "ascii"
    )


def public_key_b64() -> str:
    raw = (
        _signing_key()
        .public_key()
        .public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    )
    return base64.b64encode(raw).decode("ascii")


def embed_signing_public_key(path: Path) -> None:
    payload = (
        "# Seda Sanj release signing public key (Ed25519, raw 32 bytes, base64).\n"
        f"{public_key_b64()}\n"
    ).encode()
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    found = False
    if not zipfile.is_zipfile(path):
        inspect_artifact(path)
        try:
            with (
                tarfile.open(path, "r:gz") as source,
                tarfile.open(temporary, "w:gz", format=tarfile.USTAR_FORMAT) as target,
            ):
                for tar_entry in source:
                    if tar_entry.name == _PUBLIC_KEY_ENTRY:
                        continue
                    target.addfile(
                        tar_entry, source.extractfile(tar_entry) if tar_entry.isfile() else None
                    )
                key_entry = tarfile.TarInfo(_PUBLIC_KEY_ENTRY)
                key_entry.size = len(payload)
                key_entry.mode = 0o644
                target.addfile(key_entry, io.BytesIO(payload))
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        return
    try:
        with zipfile.ZipFile(path) as source, zipfile.ZipFile(temporary, "w") as target:
            for entry in source.infolist():
                body = source.read(entry)
                if entry.filename == _PUBLIC_KEY_ENTRY:
                    body = payload
                    found = True
                target.writestr(entry, body)
            if not found:
                target.writestr(_PUBLIC_KEY_ENTRY, payload, compress_type=zipfile.ZIP_DEFLATED)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def artifact_key(product: str, version: str) -> str:
    return f"module-releases/{product}/{version}.{'tgz' if product == PRODUCT_ISSABEL else 'zip'}"


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


def _php_floor(value: str | None) -> str | None:
    """'7.4' -> '7.4.0' so PHP versions compare like the module's x.y.z versions."""
    if not value:
        return None
    parts = re.match(r"^(\d+)\.(\d+)(?:\.(\d+))?", value)
    return f"{parts.group(1)}.{parts.group(2)}.{parts.group(3) or 0}" if parts else None


def select_update[R: ReleaseLike](
    releases: Sequence[R],
    current: str,
    *,
    freepbx: str | None = None,
    php: str | None = None,
    channel: str = "stable",
    product: str = PRODUCT_FREEPBX,
    issabel: str | None = None,
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
            if getattr(release, "product", PRODUCT_FREEPBX) == product
            and release.status == "published"
            and release.channel in allowed_channels
            and _key(release) > current_key
        ),
        key=_key,
        reverse=True,
    )
    latest: R | None = None
    for release in newer:
        # Compatibility fails closed: a host that does not report its FreePBX version cannot be
        # shown a release that declares limits, and a release never reaches a PBX outside its range.
        if product == PRODUCT_ISSABEL:
            host_major = freepbx_major(issabel)
            if host_major not in (4, 5):
                continue
            min_major = getattr(release, "min_issabel_major", None) or 4
            max_major = getattr(release, "max_issabel_major", None) or 5
        else:
            min_major = getattr(release, "min_freepbx_major", None)
            max_major = getattr(release, "max_freepbx_major", None)
        if (min_major or max_major) and not host_major:
            continue
        if min_major and host_major and host_major < min_major:
            continue
        if max_major and host_major and host_major > max_major:
            continue
        min_php = try_parse_version(_php_floor(getattr(release, "min_php_version", None)))
        host_php = try_parse_version(_php_floor(php))
        if min_php and (not host_php or host_php < min_php):
            continue
        floor = try_parse_version(release.min_from_version)
        if floor and current_key < floor:
            continue
        latest = release
        break
    if latest is None:
        return None, []
    return latest, [release for release in newer if _key(release) <= _key(latest)]
