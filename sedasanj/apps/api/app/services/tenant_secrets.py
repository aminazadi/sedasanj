from __future__ import annotations

from typing import Any, cast

from app.config import get_settings


def _fernet() -> Any:
    from cryptography.fernet import Fernet

    key = get_settings().tenant_database_master_key
    if not key:
        raise RuntimeError("tenant database master key is not configured")
    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise RuntimeError("tenant database master key must be a valid Fernet key") from exc


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
