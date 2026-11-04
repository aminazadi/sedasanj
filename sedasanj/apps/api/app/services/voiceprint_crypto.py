"""Encryption and validation of speaker voiceprints (embeddings from the Jalase-Negar app).

A voiceprint identifies a person, so it is encrypted before it reaches the database and is only
decrypted to hand it back to a paired device of the same tenant. It never appears in logs, errors
or exports. The key comes from `VOICEPRINT_ENCRYPTION_KEY`; without it nothing is stored or
served (fail closed). Several comma-separated keys allow rotation: the first one encrypts, all of
them decrypt, so a new key can be rolled out before the old one is retired.

The plaintext starts with the sample's own id, so a ciphertext copied onto another row fails to
decrypt instead of silently identifying the wrong person.
"""

from __future__ import annotations

import base64
import binascii
import math
import struct
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from app.config import get_settings

FLOAT32_BYTES = 4


class VoiceprintStorageError(RuntimeError):
    """The key is missing/invalid, or a stored value cannot be decrypted."""


class VoiceprintInvalid(ValueError):
    """The embedding sent by the app is not a usable voiceprint."""


def _fernet() -> MultiFernet:
    raw = (get_settings().voiceprint_encryption_key or "").strip()
    if not raw:
        raise VoiceprintStorageError("VOICEPRINT_ENCRYPTION_KEY is required for speaker profiles")
    keys = [part.strip() for part in raw.split(",") if part.strip()]
    try:
        return MultiFernet([Fernet(key.encode("ascii")) for key in keys])
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise VoiceprintStorageError("VOICEPRINT_ENCRYPTION_KEY must be valid Fernet keys") from exc


def storage_error() -> str:
    """Empty when voiceprints can be stored; otherwise why not (never includes the key)."""
    try:
        _fernet()
    except VoiceprintStorageError as exc:
        return str(exc)
    return ""


def decode_embedding(embedding_b64: str, dim: int) -> bytes:
    """Strict base64 of `dim` little-endian float32 values, all finite and not all zero."""
    try:
        raw = base64.b64decode(embedding_b64.encode("ascii"), validate=True)
    except (binascii.Error, UnicodeEncodeError, ValueError) as exc:
        raise VoiceprintInvalid("embedding is not valid base64") from exc
    if len(raw) != dim * FLOAT32_BYTES:
        raise VoiceprintInvalid("embedding length does not match dim")
    values = struct.unpack(f"<{dim}f", raw)
    if not all(math.isfinite(value) for value in values):
        raise VoiceprintInvalid("embedding has non-finite values")
    if not any(values):
        raise VoiceprintInvalid("embedding is all zeros")
    return raw


def encrypt_embedding(sample_id: UUID, raw: bytes) -> bytes:
    return _fernet().encrypt(sample_id.bytes + raw)


def decrypt_embedding(sample_id: UUID, token: bytes) -> bytes:
    try:
        plain = _fernet().decrypt(bytes(token))
    except InvalidToken as exc:
        raise VoiceprintStorageError("stored voiceprint cannot be decrypted") from exc
    if plain[:16] != sample_id.bytes:
        raise VoiceprintStorageError("stored voiceprint does not belong to this sample")
    return plain[16:]


def encode_embedding(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")
