from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings

PREFIX = "fernet:v1:"


def secret_storage_error() -> str:
    try:
        _fernet()
    except RuntimeError as exc:
        return str(exc)
    return ""


def _fernet() -> Fernet:
    key = (get_settings().platform_secrets_key or "").strip()
    if not key:
        raise RuntimeError("PLATFORM_SECRETS_KEY is required for provider secrets")
    try:
        return Fernet(key.encode("ascii"))
    except (TypeError, ValueError) as exc:
        raise RuntimeError("PLATFORM_SECRETS_KEY must be a valid Fernet key") from exc


def encrypt_secret(value: str) -> str:
    secret = value.strip()
    if not secret:
        return ""
    return PREFIX + _fernet().encrypt(secret.encode("utf-8")).decode("ascii")


def decrypt_secret(value: str) -> str:
    if not value:
        return ""
    if not value.startswith(PREFIX):
        raise RuntimeError("stored provider secret is not encrypted")
    try:
        return _fernet().decrypt(value[len(PREFIX) :].encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeDecodeError) as exc:
        raise RuntimeError("stored provider secret cannot be decrypted") from exc
