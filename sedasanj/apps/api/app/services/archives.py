from __future__ import annotations

import asyncio
import gzip
import stat
import zipfile
from pathlib import Path, PurePosixPath

import pyzipper
from fastapi import UploadFile

from app.config import Settings
from app.errors import ApiError

CHUNK_SIZE = 1024 * 1024
GZIP_MAGIC = b"\x1f\x8b"
ZIP_MAGICS = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
AES_EXTRA_FIELD_ID = 0x9901


def _magic(path: Path, size: int) -> bytes:
    with path.open("rb") as handle:
        return handle.read(size)


async def save_upload(upload: UploadFile, target: Path, limit: int) -> int:
    total = 0
    with target.open("wb") as handle:
        while chunk := await upload.read(CHUNK_SIZE):
            total += len(chunk)
            if total > limit:
                raise ApiError(
                    "archive_too_large", "compressed upload exceeds the configured limit"
                )
            handle.write(chunk)
    if total == 0:
        raise ApiError("unsupported_archive", "empty upload")
    return total


def _copy_limited(source: object, target: Path, limit: int) -> int:
    total = 0
    with target.open("wb") as output:
        while chunk := source.read(CHUNK_SIZE):  # type: ignore[attr-defined]
            total += len(chunk)
            if total > limit:
                raise ApiError("archive_too_large", "extracted audio exceeds the configured limit")
            output.write(chunk)
    return total


def _validate_ratio(compressed: int, extracted: int, settings: Settings) -> None:
    if compressed <= 0 or extracted > compressed * settings.max_archive_compression_ratio:
        raise ApiError("archive_unsafe", "archive compression ratio exceeds the safe limit")


def _extract_gzip(source: Path, target: Path, settings: Settings) -> None:
    if _magic(source, 2) != GZIP_MAGIC:
        raise ApiError("unsupported_archive", "API key expects a gzip upload")
    try:
        with gzip.open(source, "rb") as archive:
            extracted = _copy_limited(archive, target, settings.max_extracted_audio_bytes)
    except (gzip.BadGzipFile, EOFError, OSError) as exc:
        raise ApiError("unsupported_archive", "gzip archive is corrupt") from exc
    _validate_ratio(source.stat().st_size, extracted, settings)


def _safe_zip_entry(info: zipfile.ZipInfo) -> None:
    path = PurePosixPath(info.filename.replace("\\", "/"))
    mode = info.external_attr >> 16
    file_type = stat.S_IFMT(mode)
    if (
        info.is_dir()
        or path.is_absolute()
        or len(path.parts) != 1
        or path.name in {"", ".", ".."}
        or stat.S_ISLNK(mode)
        or file_type not in {0, stat.S_IFREG}
        or path.suffix.lower() != ".wav"
    ):
        raise ApiError("archive_unsafe", "zip must contain one regular WAV file at its root")


def _zip_aes_strength(info: zipfile.ZipInfo) -> int | None:
    offset = 0
    while offset + 4 <= len(info.extra):
        field_id = int.from_bytes(info.extra[offset : offset + 2], "little")
        field_size = int.from_bytes(info.extra[offset + 2 : offset + 4], "little")
        value_start = offset + 4
        value_end = value_start + field_size
        if value_end > len(info.extra):
            return None
        if field_id == AES_EXTRA_FIELD_ID and field_size >= 7:
            return info.extra[value_start + 4]
        offset = value_end
    return None


def _extract_zip(
    source: Path, target: Path, password: str | None, password_configured: bool, settings: Settings
) -> None:
    if _magic(source, 4) not in ZIP_MAGICS:
        raise ApiError("unsupported_archive", "API key expects a zip upload")
    try:
        with pyzipper.AESZipFile(source) as archive:
            entries = archive.infolist()
            if len(entries) != 1:
                raise ApiError("archive_unsafe", "zip must contain exactly one file")
            info = entries[0]
            _safe_zip_entry(info)
            encrypted = bool(info.flag_bits & 0x1)
            aes_strength = _zip_aes_strength(info)
            if password_configured and not encrypted:
                raise ApiError("archive_unsafe", "this API key requires an AES-256 encrypted zip")
            if encrypted and aes_strength != 3:
                raise ApiError("archive_unsafe", "only AES-256 encrypted zip files are accepted")
            if encrypted and password is None:
                raise ApiError("archive_password_required", "zip password is required")
            if info.file_size > settings.max_extracted_audio_bytes:
                raise ApiError("archive_too_large", "extracted audio exceeds the configured limit")
            _validate_ratio(max(info.compress_size, 1), info.file_size, settings)
            try:
                with archive.open(
                    info, pwd=password.encode("utf-8") if password is not None else None
                ) as member:
                    extracted = _copy_limited(member, target, settings.max_extracted_audio_bytes)
            except (RuntimeError, ValueError) as exc:
                raise ApiError("archive_password_invalid", "zip password is invalid") from exc
            if extracted != info.file_size:
                raise ApiError("unsupported_archive", "zip entry size is inconsistent")
    except ApiError:
        raise
    except (zipfile.BadZipFile, OSError, EOFError) as exc:
        raise ApiError("unsupported_archive", "zip archive is corrupt") from exc


async def prepare_agent_audio(
    upload: UploadFile,
    archive_format: str,
    password: str | None,
    password_configured: bool,
    directory: Path,
    settings: Settings,
) -> Path:
    source = directory / "upload.bin"
    target = directory / "audio.wav"
    await save_upload(upload, source, settings.max_upload_bytes)
    if archive_format == "wav":
        source.replace(target)
        return target
    if archive_format == "gzip":
        await asyncio.to_thread(_extract_gzip, source, target, settings)
        return target
    if archive_format == "zip":
        await asyncio.to_thread(
            _extract_zip, source, target, password, password_configured, settings
        )
        return target
    raise ApiError("unsupported_archive", "unsupported API key archive format")
