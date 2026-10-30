"""Signed webhook transport for assistant tools.

The assistant never calls a tool function directly: it POSTs a signed request to the tool
gateway (`POST /v1/internal/tools/{name}`), which verifies it, rebuilds the caller identity and
runs the tool inside that tenant's database scope. The secret is derived from `JWT_SECRET`, so
no administrator configuration is needed. Without `TOOL_GATEWAY_URL`, or when the API is
unreachable, the same executor runs in-process.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
import time
from typing import TYPE_CHECKING, Any
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field

from app.config import get_settings
from app.db import session_scope
from app.errors import ApiError
from app.services import assistant_tools, ratelimit

if TYPE_CHECKING:
    from app.deps import Principal

logger = logging.getLogger(__name__)

MAX_SKEW_SECONDS = 60
NONCE_TTL_SECONDS = 180
RESULT_TTL_SECONDS = 600
ALLOWED_ROLES = {"org_admin", "operator"}
_seen_nonces: dict[str, float] = {}
_cached_results: dict[str, tuple[float, dict[str, Any]]] = {}


class GatewayPrincipal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    tenant_id: UUID
    role: str
    mobile_number: str | None = None
    extension: str | None = None


class GatewayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_call_id: str = Field(min_length=1, max_length=100)
    arguments: dict[str, Any] = Field(default_factory=dict)
    principal: GatewayPrincipal
    bound_call_id: UUID | None = None
    conversation_id: UUID | None = None


def _key() -> bytes:
    secret = get_settings().jwt_secret
    return hmac.new(secret.encode(), b"sedasanj-tool-gateway-v1", hashlib.sha256).digest()


def _mac(timestamp: str, nonce: str, name: str, body: bytes) -> str:
    message = b".".join([timestamp.encode(), nonce.encode(), name.encode(), hashlib.sha256(body).digest()])
    return hmac.new(_key(), message, hashlib.sha256).hexdigest()


def sign(name: str, body: bytes) -> dict[str, str]:
    timestamp, nonce = str(int(time.time())), secrets.token_hex(16)
    return {
        "X-Tool-Timestamp": timestamp,
        "X-Tool-Nonce": nonce,
        "X-Tool-Signature": _mac(timestamp, nonce, name, body),
    }


def _forbidden() -> ApiError:
    return ApiError("forbidden", "درخواست ابزار معتبر نیست؛ دوباره پیام را بفرستید")


async def _remember_nonce(nonce: str) -> bool:
    redis = ratelimit._get_redis()
    if redis is not None:
        return bool(await redis.set(f"tool-gw:nonce:{nonce}", "1", nx=True, ex=NONCE_TTL_SECONDS))
    now = time.time()
    for old in [key for key, expires in _seen_nonces.items() if expires < now]:
        del _seen_nonces[old]
    if nonce in _seen_nonces:
        return False
    _seen_nonces[nonce] = now + NONCE_TTL_SECONDS
    return True


async def verify(name: str, body: bytes, headers: Any) -> None:
    timestamp = headers.get("x-tool-timestamp", "")
    nonce = headers.get("x-tool-nonce", "")
    signature = headers.get("x-tool-signature", "")
    if not timestamp.isdigit() or not nonce or len(nonce) > 64 or not signature:
        raise _forbidden()
    if abs(time.time() - int(timestamp)) > MAX_SKEW_SECONDS:
        raise _forbidden()
    if not hmac.compare_digest(signature, _mac(timestamp, nonce, name, body)):
        raise _forbidden()
    if not await _remember_nonce(nonce):
        raise _forbidden()


async def _cached(tenant_id: UUID, tool_call_id: str) -> dict[str, Any] | None:
    key = f"tool-gw:result:{tenant_id}:{tool_call_id}"
    redis = ratelimit._get_redis()
    if redis is not None:
        raw = await redis.get(key)
        return json.loads(raw) if raw else None
    entry = _cached_results.get(key)
    return entry[1] if entry and entry[0] > time.time() else None


async def _store(tenant_id: UUID, tool_call_id: str, payload: dict[str, Any]) -> None:
    key = f"tool-gw:result:{tenant_id}:{tool_call_id}"
    redis = ratelimit._get_redis()
    if redis is not None:
        await redis.set(key, json.dumps(payload, default=str), ex=RESULT_TTL_SECONDS)
        return
    _cached_results[key] = (time.time() + RESULT_TTL_SECONDS, payload)


async def execute_local(
    name: str,
    arguments: dict[str, Any],
    principal: Principal,
    bound_call_id: UUID | None,
    conversation_id: UUID | None,
) -> tuple[dict[str, Any], int]:
    """Run one tool in the caller's tenant scope; remove an export whose commit failed."""
    assert principal.tenant_id is not None
    result: dict[str, Any] | None = None
    try:
        async with session_scope(principal.tenant_id) as tool_session:
            result, duration = await assistant_tools.execute(
                name,
                arguments,
                assistant_tools.ToolContext(tool_session, principal, bound_call_id, conversation_id),
            )
        return result, duration
    except BaseException:
        if name == "export_data" and result is not None and result.get("file"):
            from app.services.storage import get_storage

            file = result["file"]
            key = f"exports/{principal.tenant_id}/{UUID(file['export_id'])}.{file['format']}"
            try:
                await get_storage().delete(key)
            except Exception:
                logger.error("uncommitted assistant export cleanup failed; check object storage")
        raise


async def handle(name: str, request: GatewayRequest) -> dict[str, Any]:
    """Server side of the webhook: idempotent per tool_call_id."""
    from app.deps import Principal

    if name not in assistant_tools.TOOL_BY_NAME:
        raise ApiError("not_found", "ابزار پیدا نشد؛ فهرست ابزارها را تازه کنید")
    if request.principal.role not in ALLOWED_ROLES:
        raise _forbidden()
    cached = await _cached(request.principal.tenant_id, request.tool_call_id)
    if cached is not None:
        return cached
    principal = Principal(
        kind="user",
        id=request.principal.id,
        tenant_id=request.principal.tenant_id,
        role=request.principal.role,
        mobile_number=request.principal.mobile_number,
        extension=request.principal.extension,
    )
    result, duration = await execute_local(
        name, request.arguments, principal, request.bound_call_id, request.conversation_id
    )
    payload = {"result": result, "duration_ms": duration}
    await _store(request.principal.tenant_id, request.tool_call_id, payload)
    return payload


async def dispatch(
    name: str,
    tool_call_id: str,
    arguments: dict[str, Any],
    principal: Principal,
    bound_call_id: UUID | None,
    conversation_id: UUID | None = None,
) -> tuple[dict[str, Any], int]:
    """Client side of the webhook used by the assistant."""
    settings = get_settings()
    assert principal.tenant_id is not None
    base = (settings.tool_gateway_url or "").rstrip("/")
    if not base:
        return await execute_local(name, arguments, principal, bound_call_id, conversation_id)
    body = GatewayRequest(
        tool_call_id=tool_call_id,
        arguments=arguments,
        principal=GatewayPrincipal(
            id=principal.id,
            tenant_id=principal.tenant_id,
            role=principal.role,
            mobile_number=principal.mobile_number,
            extension=principal.extension,
        ),
        bound_call_id=bound_call_id,
        conversation_id=conversation_id,
    ).model_dump_json().encode()
    url = f"{base}/v1/internal/tools/{name}"
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=settings.tool_gateway_timeout_seconds) as client:
                response = await client.post(
                    url,
                    content=body,
                    headers={**sign(name, body), "Content-Type": "application/json"},
                )
        except httpx.ConnectError as exc:
            last_error = exc
            break
        except httpx.TransportError as exc:
            last_error = exc
            continue
        if response.status_code >= 500 and attempt == 0:
            continue
        if response.status_code != 200:
            try:
                error = response.json()["error"]
                raise ApiError(
                    error["code"] if error["code"] in _client_codes() else "internal",
                    str(error["message"]),
                )
            except (ValueError, KeyError, TypeError):
                raise ApiError(
                    "internal", "سرویس ابزارها خطا داد؛ چند لحظه بعد دوباره تلاش کنید"
                ) from None
        data = response.json()
        return data["result"], int(data["duration_ms"])
    if isinstance(last_error, httpx.ConnectError):
        logger.warning("tool gateway unreachable; running assistant tool in-process")
        return await execute_local(name, arguments, principal, bound_call_id, conversation_id)
    raise ApiError("worker_timeout", "سرویس ابزارها پاسخ نداد؛ چند لحظه بعد دوباره تلاش کنید")


def _client_codes() -> set[str]:
    from app.errors import ERROR_STATUS

    return set(ERROR_STATUS)
