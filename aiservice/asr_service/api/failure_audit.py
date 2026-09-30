"""ASGI middleware that records every unsuccessful user-facing API response."""

import json

from asr_service.infrastructure.failures import record_failure


def _classification(status_code):
    return {
        400: ("validation", "invalid_request"),
        401: ("authentication", "authentication_failed"),
        403: ("authorization", "access_denied"),
        404: ("routing", "not_found"),
        409: ("conflict", "conflict"),
        413: ("payload", "payload_too_large"),
        422: ("validation", "validation_failed"),
        429: ("rate_limit", "rate_limit_exceeded"),
        503: ("capacity", "service_unavailable"),
    }.get(status_code, ("server" if status_code >= 500 else "request", f"http_{status_code}"))


def _error_body(raw, fallback_reason):
    if not raw:
        return fallback_reason, None
    try:
        payload = json.loads(raw.decode("utf-8", errors="replace"))
    except (ValueError, TypeError):
        return fallback_reason, None
    if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
        error = payload["error"]
        reason = error.get("code") or error.get("type") or fallback_reason
        return str(reason), str(error.get("message") or "") or None
    detail = payload.get("detail") if isinstance(payload, dict) else None
    if isinstance(detail, str):
        return fallback_reason, detail
    if isinstance(detail, list):
        messages = []
        for item in detail[:20]:
            if not isinstance(item, dict):
                continue
            location = ".".join(str(value) for value in item.get("loc", ()))
            messages.append(f"{location}: {item.get('msg', 'Invalid value')}".strip(": "))
        return fallback_reason, "; ".join(messages)[:4000] or None
    return fallback_reason, None


class RequestFailureAuditMiddleware:
    """Record status >= 400 and unhandled exceptions for ``/v1/*`` requests."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or not scope.get("path", "").startswith("/v1/"):
            return await self.app(scope, receive, send)
        status_code = None
        body = bytearray()

        async def audited_send(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            elif message["type"] == "http.response.body" and len(body) < 16384:
                body.extend(message.get("body", b"")[: 16384 - len(body)])
            await send(message)

        try:
            await self.app(scope, receive, audited_send)
        except Exception as exc:
            if not scope.get("asr_failure_recorded"):
                record_failure(
                    status_code=500,
                    phase="server",
                    reason="unhandled_exception",
                    detail=f"{type(exc).__name__}: {exc}",
                    scope=scope,
                )
                scope["asr_failure_recorded"] = True
            raise
        if status_code is not None and status_code >= 400 and not scope.get("asr_failure_recorded"):
            phase, fallback_reason = _classification(status_code)
            reason, detail = _error_body(bytes(body), fallback_reason)
            record_failure(
                status_code=status_code,
                phase=phase,
                reason=reason,
                detail=detail,
                scope=scope,
            )
