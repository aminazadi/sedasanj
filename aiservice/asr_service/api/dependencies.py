"""Unified bearer authentication for the master administrator and issued API keys."""

import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import Depends, Header, HTTPException

from asr_service.infrastructure.storage import execute, now, row


@dataclass(frozen=True)
class Principal:
    is_admin: bool
    key_id: int | None = None
    scopes: tuple[str, ...] = ()
    models: tuple[str, ...] | None = None


_rate_lock = threading.Lock()
_rate_windows: dict[int, deque[float]] = defaultdict(deque)


def hash_key(value: str):
    pepper = os.getenv("ASR_API_KEY_PEPPER", "")
    return hashlib.sha256((pepper + value).encode()).hexdigest()


def issue_key():
    value = "pasr_" + secrets.token_urlsafe(32)
    return value, value[:13], hash_key(value)


def _credentials(authorization: str | None):
    if not authorization:
        raise HTTPException(401, "Missing bearer API key", headers={"WWW-Authenticate": "Bearer"})
    scheme, separator, value = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer" or not value.strip():
        raise HTTPException(401, "Invalid API key", headers={"WWW-Authenticate": "Bearer"})
    return value.strip()


def _rate_limit(key_id: int, limit: int | None):
    if not limit:
        return
    timestamp = time.monotonic()
    with _rate_lock:
        window = _rate_windows[key_id]
        while window and window[0] <= timestamp - 60:
            window.popleft()
        if len(window) >= limit:
            retry = max(1, int(60 - (timestamp - window[0])))
            raise HTTPException(429, "Rate limit exceeded", headers={"Retry-After": str(retry)})
        window.append(timestamp)


def authorize(authorization: str | None = Header(default=None)):
    """Authenticate callers; only ASR_API_KEY is an administrator credential."""

    value = _credentials(authorization)
    master = os.getenv("ASR_API_KEY", "")
    if master and hmac.compare_digest(value, master):
        return Principal(is_admin=True, scopes=("*",))
    record = row("SELECT * FROM api_keys WHERE key_hash=?", (hash_key(value),))
    if not record or not record["enabled"] or record.get("revoked_at"):
        raise HTTPException(401, "Invalid API key", headers={"WWW-Authenticate": "Bearer"})
    if record.get("expires_at"):
        try:
            expiry = datetime.fromisoformat(record["expires_at"].replace("Z", "+00:00"))
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            expired = expiry <= datetime.now(timezone.utc)
        except (ValueError, TypeError):
            expired = True
        if expired:
            raise HTTPException(401, "API key has expired", headers={"WWW-Authenticate": "Bearer"})
    _rate_limit(record["id"], record.get("rate_limit_per_minute"))
    execute("UPDATE api_keys SET last_used_at=? WHERE id=?", (now(), record["id"]))
    scopes = tuple(json.loads(record["scopes_json"] or "[]"))
    models = tuple(json.loads(record["models_json"])) if record.get("models_json") else None
    return Principal(False, record["id"], scopes, models)


def authorize_admin(principal: Principal = Depends(authorize)):
    if not principal.is_admin:
        raise HTTPException(403, "Administrator API key required")
    return principal


def require_access(principal: Principal, scope: str, models=()):
    if principal.is_admin:
        return
    allowed = "*" in principal.scopes or "inference" in principal.scopes or scope in principal.scopes
    if scope == "inference":
        allowed = allowed or bool({"chat", "transcription", "text", "decision"} & set(principal.scopes))
    if not allowed:
        raise HTTPException(403, f"API key does not allow {scope}")
    if principal.models is not None and any(model not in principal.models for model in models):
        raise HTTPException(403, "API key does not allow one or more requested models")
