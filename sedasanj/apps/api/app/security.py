import base64
import binascii
import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from urllib.parse import quote
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.config import get_settings

_hasher = PasswordHasher()
API_KEY_PREFIX = "sk_live_"
JWT_ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def totp_code(secret: str, counter: int, digits: int = 6) -> str:
    key = base64.b32decode(secret.upper() + "=" * (-len(secret) % 8))
    digest = hmac.new(key, counter.to_bytes(8, "big"), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = int.from_bytes(digest[offset : offset + 4], "big") & 0x7FFFFFFF
    return str(value % (10**digits)).zfill(digits)


def verify_totp(secret: str, code: str | None, *, period: int = 30, drift: int = 1) -> bool:
    """RFC 6238 verification with a one-step window either side (§12)."""
    if not code or not code.isdigit() or len(code) != 6:
        return False
    counter = int(datetime.now(UTC).timestamp()) // period
    try:
        expected = [totp_code(secret, counter + offset) for offset in range(-drift, drift + 1)]
    except (binascii.Error, ValueError):
        return False
    return any(hmac.compare_digest(candidate, code) for candidate in expected)


def generate_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def totp_uri(secret: str, email: str) -> str:
    label = quote("SedaSanj:" + email, safe="")
    return (
        f"otpauth://totp/{label}?secret={secret}&issuer=SedaSanj"
        "&algorithm=SHA1&digits=6&period=30"
    )


def generate_api_key() -> tuple[str, str, str]:
    """Return (secret, prefix, hash). The secret is shown to the caller exactly once."""
    secret = API_KEY_PREFIX + secrets.token_urlsafe(32)
    return materialize_api_key(secret)


def materialize_api_key(secret: str) -> tuple[str, str, str]:
    """Return (secret, prefix, hash) for an existing or newly chosen API key string."""
    cleaned = secret.strip()
    if not cleaned.startswith(API_KEY_PREFIX) or len(cleaned) <= len(API_KEY_PREFIX) + 4:
        raise ValueError("api key must look like sk_live_…")
    return cleaned, cleaned[: len(API_KEY_PREFIX) + 4], hash_api_key(cleaned)


def hash_api_key(secret: str) -> str:
    pepper = get_settings().api_key_pepper
    return hashlib.sha256((secret + pepper).encode()).hexdigest()


def generate_refresh_token() -> tuple[str, str]:
    token = secrets.token_urlsafe(48)
    return token, hash_refresh_token(token)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_access_token(
    *,
    subject: UUID,
    tenant_id: UUID | None,
    role: str,
    actor: Literal["user", "staff"] = "user",
) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    claims: dict[str, Any] = {
        "sub": str(subject),
        "tenant_id": str(tenant_id) if tenant_id else None,
        "role": role,
        "typ": "access",
        "actor": actor,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.access_token_ttl_minutes)).timestamp()),
    }
    return jwt.encode(claims, settings.jwt_secret, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    claims: dict[str, Any] = jwt.decode(token, settings.jwt_secret, algorithms=[JWT_ALGORITHM])
    if claims.get("typ") != "access":
        raise jwt.InvalidTokenError("not an access token")
    return claims


def sign_webhook(secret: str, timestamp: str, body: bytes) -> str:
    mac = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256)
    return "sha256=" + mac.hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)
