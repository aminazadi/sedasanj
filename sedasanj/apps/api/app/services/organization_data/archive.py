from __future__ import annotations

import base64
import binascii
import hashlib
import io
import json
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZIP_STORED, BadZipFile, ZipFile, ZipInfo

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from app.errors import ApiError

MAGIC = b"SEDASANJ\x01"
CHUNK_SIZE = 1024 * 1024
MAX_ROW_BYTES = 4 * CHUNK_SIZE
MAX_ROWS = 500_000
MAX_MANIFEST_BYTES = 8 * CHUNK_SIZE
MAX_ZIP_DIRECTORY_BYTES = 96 * CHUNK_SIZE
_ENTRY = re.compile(r"(?:manifest\.json|rows/[a-z_]+\.ndjson|media/[a-z_]+/[0-9a-f]{32})")


def invalid_archive() -> ApiError:
    return ApiError(
        "org_archive_invalid",
        "فایل یا کلید بازیابی معتبر نیست. فایل اصلی و کلید همان بک‌آپ را دوباره انتخاب کنید.",
    )


def archive_too_large() -> ApiError:
    return ApiError(
        "org_archive_too_large",
        "حجم فایل یا داده‌های داخل آن بیش از حد مجاز است. سقف بک‌آپ را با مدیر سامانه بررسی کنید.",
    )


def recovery_key(value: str) -> bytes:
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", value):
        raise invalid_archive()
    try:
        key = base64.b64decode(value + "=", altchars=b"-_", validate=True)
    except (ValueError, binascii.Error) as exc:
        raise invalid_archive() from exc
    if len(key) != 32:
        raise invalid_archive()
    return key


def seal(source: Path, target: Path, key: bytes, limit: int) -> tuple[int, str]:
    if source.stat().st_size + len(MAGIC) + 28 > limit:
        raise archive_too_large()
    nonce = os.urandom(12)
    header = MAGIC + nonce
    encryptor = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
    encryptor.authenticate_additional_data(header)
    digest = hashlib.sha256(header)
    with source.open("rb") as incoming, target.open("wb") as outgoing:
        outgoing.write(header)
        while block := incoming.read(CHUNK_SIZE):
            ciphertext = encryptor.update(block)
            digest.update(ciphertext)
            outgoing.write(ciphertext)
        encryptor.finalize()
        digest.update(encryptor.tag)
        outgoing.write(encryptor.tag)
    return target.stat().st_size, digest.hexdigest()


def unseal(source: Path, target: Path, key: bytes, limit: int) -> None:
    size = source.stat().st_size
    if size > limit:
        raise archive_too_large()
    try:
        with source.open("rb") as incoming:
            header = incoming.read(len(MAGIC) + 12)
            remaining = size - len(header) - 16
            if not header.startswith(MAGIC) or remaining <= 0:
                raise invalid_archive()
            incoming.seek(-16, os.SEEK_END)
            tag = incoming.read(16)
            incoming.seek(len(header))
            decryptor = Cipher(algorithms.AES(key), modes.GCM(header[-12:], tag)).decryptor()
            decryptor.authenticate_additional_data(header)
            with target.open("wb") as outgoing:
                while remaining:
                    block = incoming.read(min(remaining, CHUNK_SIZE))
                    if not block:
                        raise invalid_archive()
                    remaining -= len(block)
                    outgoing.write(decryptor.update(block))
                decryptor.finalize()
    except (InvalidTag, ValueError) as exc:
        target.unlink(missing_ok=True)
        raise invalid_archive() from exc
    except BaseException:
        target.unlink(missing_ok=True)
        raise


def json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()


class _BoundedZipInput(io.BufferedReader):
    def read(self, size: int | None = -1, /) -> bytes:
        # ZipFile loads the entire central directory before the per-entry checks run.
        if size is not None and size > MAX_ZIP_DIRECTORY_BYTES:
            raise archive_too_large()
        result = super().read(
            size if size is not None and size >= 0 else MAX_ZIP_DIRECTORY_BYTES + 1
        )
        if len(result) > MAX_ZIP_DIRECTORY_BYTES:
            raise archive_too_large()
        return result


@contextmanager
def open_zip(path: Path) -> Iterator[ZipFile]:
    with _BoundedZipInput(path.open("rb", buffering=0)) as source, ZipFile(source) as archive:
        yield archive


def checked_entries(archive: ZipFile, limit: int) -> set[str]:
    entries: set[str] = set()
    size = 0
    for member in archive.infolist():
        name = member.filename
        size += member.file_size
        if size > limit or len(entries) >= MAX_ROWS + 256:
            raise archive_too_large()
        if (
            name in entries
            or not _ENTRY.fullmatch(name)
            or member.is_dir()
            or member.compress_type not in {ZIP_STORED, ZIP_DEFLATED}
            or member.flag_bits & 1
        ):
            raise invalid_archive()
        entries.add(name)
    if "manifest.json" not in entries:
        raise invalid_archive()
    return entries


def read_manifest(archive: ZipFile) -> dict[str, Any]:
    info = archive.getinfo("manifest.json")
    if info.file_size > MAX_MANIFEST_BYTES:
        raise archive_too_large()
    try:
        manifest = json.loads(archive.read(info))
    except (BadZipFile, UnicodeError, ValueError) as exc:
        raise invalid_archive() from exc
    if not isinstance(manifest, dict) or manifest.get("version") != 1:
        raise invalid_archive()
    return manifest


def records(archive: ZipFile, member: str) -> Iterator[dict[str, Any]]:
    try:
        with archive.open(member) as source:
            while line := source.readline(MAX_ROW_BYTES + 1):
                if len(line) > MAX_ROW_BYTES:
                    raise archive_too_large()
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise invalid_archive()
                yield value
    except (BadZipFile, UnicodeError, ValueError) as exc:
        raise invalid_archive() from exc


def media_member(name: str) -> ZipInfo:
    info = ZipInfo(name)
    info.compress_type = ZIP_STORED
    return info
