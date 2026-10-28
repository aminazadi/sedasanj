from __future__ import annotations

import base64
import hashlib
from typing import Any, cast

from app.config import get_settings


def normalize_master_key(key: str) -> bytes:
    normalized = key.strip()
    if not normalized:
        raise RuntimeError("tenant database master key is not configured")
    try:
        decoded = base64.urlsafe_b64decode(normalized.encode("ascii"))
    except (ValueError, UnicodeEncodeError):
        decoded = b""
    if len(decoded) == 32:
        return normalized.encode("ascii")
    return base64.urlsafe_b64encode(hashlib.sha256(normalized.encode("utf-8")).digest())


def _fernet() -> Any:
    from cryptography.fernet import Fernet

    key = get_settings().tenant_database_master_key
    if not key:
        raise RuntimeError("tenant database master key is not configured")
    return Fernet(normalize_master_key(key))


def encrypt_dsn(dsn: str) -> str:
    fernet = _fernet()
    return cast(str, fernet.encrypt(dsn.encode("utf-8")).decode("ascii"))


def decrypt_dsn(ciphertext: str) -> str:
    from cryptography.fernet import InvalidToken

    try:
        fernet = _fernet()
        return cast(str, fernet.decrypt(ciphertext.encode("ascii")).decode("utf-8"))
    except (InvalidToken, UnicodeError) as exc:
        raise RuntimeError("tenant database credential cannot be decrypted") from exc
