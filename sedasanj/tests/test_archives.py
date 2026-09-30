from __future__ import annotations

import gzip
import io
import zipfile
from pathlib import Path

import pytest
import pyzipper
from fastapi import UploadFile

from app.config import Settings
from app.errors import ApiError
from app.services.archives import prepare_agent_audio


def _settings(**changes: object) -> Settings:
    values: dict[str, object] = {
        "jwt_secret": "x" * 40,
        "api_key_pepper": "y" * 40,
        "max_archive_compression_ratio": 1000,
    }
    values.update(changes)
    return Settings(**values)  # type: ignore[arg-type]


async def _prepare(
    tmp_path: Path,
    payload: bytes,
    archive_format: str,
    password: str | None = None,
    password_configured: bool = False,
) -> bytes:
    upload = UploadFile(file=io.BytesIO(payload), filename=f"call.{archive_format}")
    path = await prepare_agent_audio(
        upload,
        archive_format,
        password,
        password_configured,
        tmp_path,
        _settings(),
    )
    return path.read_bytes()


async def test_prepare_gzip_extracts_one_wav(tmp_path: Path, wav_factory) -> None:
    wav = wav_factory(seconds=0.2)
    assert await _prepare(tmp_path, gzip.compress(wav), "gzip") == wav


async def test_prepare_rejects_format_magic_mismatch(tmp_path: Path) -> None:
    with pytest.raises(ApiError) as excinfo:
        await _prepare(tmp_path, b"PK-not-gzip", "gzip")
    assert excinfo.value.code == "unsupported_archive"


async def test_prepare_aes_zip_with_password(tmp_path: Path, wav_factory) -> None:
    payload = io.BytesIO()
    with pyzipper.AESZipFile(
        payload,
        "w",
        compression=pyzipper.ZIP_DEFLATED,
        encryption=pyzipper.WZ_AES,
    ) as archive:
        archive.setpassword(b"Strong-Passphrase-2026")
        archive.setencryption(pyzipper.WZ_AES, nbits=256)
        archive.writestr("call.wav", wav_factory(seconds=0.2))
    extracted = await _prepare(
        tmp_path,
        payload.getvalue(),
        "zip",
        "Strong-Passphrase-2026",
        True,
    )
    assert extracted.startswith(b"RIFF")


async def test_prepare_unencrypted_zip(tmp_path: Path, wav_factory) -> None:
    wav = wav_factory(seconds=0.2)
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("call.wav", wav)
    assert await _prepare(tmp_path, payload.getvalue(), "zip") == wav


async def test_prepare_rejects_wrong_zip_password(tmp_path: Path, wav_factory) -> None:
    payload = io.BytesIO()
    with pyzipper.AESZipFile(payload, "w", encryption=pyzipper.WZ_AES) as archive:
        archive.setpassword(b"Strong-Passphrase-2026")
        archive.setencryption(pyzipper.WZ_AES, nbits=256)
        archive.writestr("call.wav", wav_factory(seconds=0.2))
    with pytest.raises(ApiError) as excinfo:
        await _prepare(tmp_path, payload.getvalue(), "zip", "wrong-password", True)
    assert excinfo.value.code == "archive_password_invalid"


async def test_prepare_rejects_aes_128_zip(tmp_path: Path, wav_factory) -> None:
    payload = io.BytesIO()
    with pyzipper.AESZipFile(payload, "w", encryption=pyzipper.WZ_AES) as archive:
        archive.setpassword(b"Strong-Passphrase-2026")
        archive.setencryption(pyzipper.WZ_AES, nbits=128)
        archive.writestr("call.wav", wav_factory(seconds=0.2))
    with pytest.raises(ApiError) as excinfo:
        await _prepare(
            tmp_path,
            payload.getvalue(),
            "zip",
            "Strong-Passphrase-2026",
            True,
        )
    assert excinfo.value.code == "archive_unsafe"


async def test_prepare_rejects_multiple_or_unsafe_zip_entries(tmp_path: Path, wav_factory) -> None:
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("../call.wav", wav_factory(seconds=0.2))
    with pytest.raises(ApiError) as excinfo:
        await _prepare(tmp_path, payload.getvalue(), "zip")
    assert excinfo.value.code == "archive_unsafe"


async def test_prepare_rejects_zip_bomb_ratio(tmp_path: Path) -> None:
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("call.wav", b"0" * 1_000_000)
    upload = UploadFile(file=io.BytesIO(payload.getvalue()), filename="call.zip")
    with pytest.raises(ApiError) as excinfo:
        await prepare_agent_audio(
            upload,
            "zip",
            None,
            False,
            tmp_path,
            _settings(max_archive_compression_ratio=10),
        )
    assert excinfo.value.code == "archive_unsafe"
