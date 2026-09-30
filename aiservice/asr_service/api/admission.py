"""ASGI admission control that rejects overload before reading request bodies."""

import asyncio
import threading
import time

from starlette.responses import JSONResponse

from asr_service.infrastructure.failures import record_failure
from asr_service.services.ingress import (
    HTTP_ADMISSION_WAIT_SECONDS,
    HTTP_MAX_BODY_BYTES,
    HTTP_MAX_JSON_BODY_BYTES,
    HTTP_MAX_IN_FLIGHT,
    SYNC_CHAT_MAX_IN_FLIGHT,
)


class IngressAdmissionMiddleware:
    _audit_lock = threading.Lock()
    _last_audit = {}

    def __init__(self, app):
        self.app = app
        self.slots = asyncio.Semaphore(HTTP_MAX_IN_FLIGHT)
        self.sync_chat_slots = asyncio.Semaphore(SYNC_CHAT_MAX_IN_FLIGHT)

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or scope.get("path") in {
            "/health",
            "/live",
            "/ready",
        }:
            return await self.app(scope, receive, send)
        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", ())
        }
        raw_length = headers.get("content-length")
        if (
            raw_length is None
            and scope.get("method") in {"POST", "PUT", "PATCH"}
            and headers.get("transfer-encoding")
        ):
            self._record(scope, 411, "content_length_required")
            return await JSONResponse(
                {"detail": "Content-Length is required"}, status_code=411
            )(scope, receive, send)
        try:
            content_length = int(raw_length or "0")
        except ValueError:
            content_length = -1
        maximum = (
            HTTP_MAX_BODY_BYTES
            if scope.get("path") == "/v1/audio/transcriptions"
            else HTTP_MAX_JSON_BODY_BYTES
        )
        if content_length < 0 or content_length > maximum:
            self._record(scope, 413, "request_body_too_large")
            return await JSONResponse(
                {"detail": "Request body is too large"}, status_code=413
            )(scope, receive, send)
        try:
            await asyncio.wait_for(
                self.slots.acquire(), timeout=HTTP_ADMISSION_WAIT_SECONDS
            )
        except TimeoutError:
            self._record(scope, 503, "http_admission_full")
            return await JSONResponse(
                {"detail": "Service admission capacity is full"},
                status_code=503,
                headers={"Retry-After": "2"},
            )(scope, receive, send)
        chat_acquired = False
        if scope.get("path") == "/v1/chat/completions":
            try:
                await asyncio.wait_for(
                    self.sync_chat_slots.acquire(),
                    timeout=HTTP_ADMISSION_WAIT_SECONDS,
                )
                chat_acquired = True
            except TimeoutError:
                self.slots.release()
                self._record(scope, 503, "sync_chat_admission_full")
                return await JSONResponse(
                    {"detail": "Synchronous chat capacity is full"},
                    status_code=503,
                    headers={"Retry-After": "2"},
                )(scope, receive, send)
        try:
            return await self.app(scope, receive, send)
        finally:
            if chat_acquired:
                self.sync_chat_slots.release()
            self.slots.release()

    @classmethod
    def _record(cls, scope, status_code, reason):
        if not scope.get("path", "").startswith("/v1/"):
            return
        stamp = time.monotonic()
        with cls._audit_lock:
            if stamp - cls._last_audit.get(reason, 0) < 1:
                return
            cls._last_audit[reason] = stamp
        record_failure(
            status_code=status_code,
            phase="capacity",
            reason=reason,
            scope=scope,
        )
        scope["asr_failure_recorded"] = True
