"""Database-backed CORS and client-IP allowlist middleware."""

import ipaddress
import logging
from starlette.responses import JSONResponse, Response

from asr_service.infrastructure.failures import record_failure, request_metadata
from asr_service.infrastructure.storage import execute, now


logger = logging.getLogger("asr_service.security")


def record_rejection(scope, headers, reason, detail):
    """Persist safe request metadata for an allowlist rejection."""

    # Retain the original security audit stream for compatibility, while the
    # unified failure stream below powers the new “all unsuccessful requests”
    # screen.  Neither store receives credentials or request bodies.
    metadata = request_metadata(scope)
    try:
        execute(
            """INSERT INTO security_rejections(
               created_at,reason,client_ip,origin,method,path,query_string,
               x_forwarded_for,x_real_ip,forwarded,user_agent,requested_method,
               requested_headers,detail) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                now(), reason, metadata.get("client_ip"), metadata.get("origin"),
                metadata.get("method"), metadata.get("path"), metadata.get("query_string"),
                metadata.get("x_forwarded_for"), metadata.get("x_real_ip"),
                metadata.get("forwarded"), metadata.get("user_agent"),
                metadata.get("requested_method"), metadata.get("requested_headers"), detail,
            ),
        )
    except Exception:
        # A logging failure must never change access-control behavior.
        logger.exception("Failed to persist security rejection")
    recorded = record_failure(
        status_code=403,
        phase="network_policy",
        reason=reason,
        detail=detail,
        scope=scope,
    )
    if recorded is not None:
        scope["asr_failure_recorded"] = True


class DynamicCORSMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        from .routers.security import get_cors_policy
        try:
            policy = get_cors_policy()
        except Exception:
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        headers = {key.decode().lower(): value.decode() for key, value in scope.get("headers", [])}
        origin = headers.get("origin")
        allowed_origin = bool(origin) and ("*" in policy.allowed_origins or origin in policy.allowed_origins)
        method_allowed = scope["method"] in policy.allowed_methods or scope["method"] == "OPTIONS"
        if path.startswith("/v1/") and policy.allowed_ips:
            client = (scope.get("client") or ("", 0))[0]
            try:
                permitted = any(ipaddress.ip_address(client) in ipaddress.ip_network(value, strict=False) for value in policy.allowed_ips)
            except ValueError:
                permitted = False
            if not permitted:
                record_rejection(scope, headers, "ip_not_allowed", "Client IP is not in the configured allowlist")
                logger.warning(
                    "IP allowlist rejected request: client=%r x_forwarded_for=%r "
                    "x_real_ip=%r forwarded=%r",
                    client,
                    headers.get("x-forwarded-for"),
                    headers.get("x-real-ip"),
                    headers.get("forwarded"),
                )
                return await JSONResponse({"error": {"message": "Client IP is not allowed", "type": "access_denied", "param": None, "code": "ip_not_allowed"}}, status_code=403)(scope, receive, send)
        if path.startswith("/v1/") and origin and not allowed_origin:
            record_rejection(scope, headers, "origin_not_allowed", "Origin is not in the configured allowlist")
            return await JSONResponse({"detail": "Origin is not allowed"}, status_code=403)(scope, receive, send)
        if scope["method"] == "OPTIONS" and origin and headers.get("access-control-request-method"):
            requested_method = headers["access-control-request-method"].upper()
            requested_headers = {item.strip().lower() for item in headers.get("access-control-request-headers", "").split(",") if item.strip()}
            permitted_headers = {item.lower() for item in policy.allowed_headers}
            if requested_method not in policy.allowed_methods or not requested_headers <= permitted_headers:
                record_rejection(scope, headers, "cors_policy_not_allowed", "Requested CORS method or headers are not allowed")
                return await JSONResponse({"detail": "Requested CORS method or headers are not allowed"}, status_code=403)(scope, receive, send)
            response_headers = self._headers(policy, origin)
            response_headers["Access-Control-Allow-Methods"] = ", ".join(policy.allowed_methods)
            response_headers["Access-Control-Allow-Headers"] = ", ".join(policy.allowed_headers)
            return await Response(status_code=204, headers=response_headers)(scope, receive, send)

        async def cors_send(message):
            if message["type"] == "http.response.start" and allowed_origin and method_allowed:
                extra = [(key.lower().encode(), value.encode()) for key, value in self._headers(policy, origin).items()]
                message.setdefault("headers", []).extend(extra)
            await send(message)
        return await self.app(scope, receive, cors_send)

    @staticmethod
    def _headers(policy, origin):
        chosen = "*" if "*" in policy.allowed_origins and not policy.allow_credentials else origin
        result = {"Access-Control-Allow-Origin": chosen, "Vary": "Origin"}
        if policy.allow_credentials:
            result["Access-Control-Allow-Credentials"] = "true"
        return result
