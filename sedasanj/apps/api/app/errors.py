from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

ERROR_STATUS: dict[str, int] = {
    "unauthorized": status.HTTP_401_UNAUTHORIZED,
    "forbidden": status.HTTP_403_FORBIDDEN,
    "insufficient_credit": status.HTTP_402_PAYMENT_REQUIRED,
    "quota_exceeded": status.HTTP_402_PAYMENT_REQUIRED,
    "subscription_inactive": status.HTTP_402_PAYMENT_REQUIRED,
    "tenant_suspended": status.HTTP_403_FORBIDDEN,
    "conflict_idempotency": status.HTTP_409_CONFLICT,
    "unsupported_audio": status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
    "unsupported_archive": status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
    "archive_password_required": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "archive_password_invalid": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "archive_unsafe": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "archive_too_large": status.HTTP_413_CONTENT_TOO_LARGE,
    "not_found": status.HTTP_404_NOT_FOUND,
    "rate_limited": status.HTTP_429_TOO_MANY_REQUESTS,
    "invalid_request": 422,
    "assistant_tool_disabled": 422,
    "assistant_tool_plan_invalid": 422,
    "assistant_export_unavailable": 503,
    "export_expired": 410,
    "export_too_large": 422,
    "conflict": status.HTTP_409_CONFLICT,
    "subscription_exists": status.HTTP_409_CONFLICT,
    "change_conflict": status.HTTP_409_CONFLICT,
    "plan_not_sellable": 422,
    "plan_code_exists": status.HTTP_409_CONFLICT,
    "plan_in_use": status.HTTP_409_CONFLICT,
    "order_amount_too_large": 422,
    "payment_gateway_unavailable": status.HTTP_502_BAD_GATEWAY,
    "payment_method_unavailable": status.HTTP_409_CONFLICT,
    "worker_timeout": status.HTTP_504_GATEWAY_TIMEOUT,
    "internal": status.HTTP_500_INTERNAL_SERVER_ERROR,
}

RETRYABLE_CODES = {
    "insufficient_credit",
    "quota_exceeded",
    "subscription_inactive",
    "rate_limited",
    "internal",
    "payment_gateway_unavailable",
}


class ApiError(Exception):
    """Error carrying one of the §7.3 codes."""

    def __init__(self, code: str, message: str, retryable: bool | None = None) -> None:
        if code not in ERROR_STATUS:
            raise ValueError(f"unknown error code {code}")
        self.code = code
        self.message = message
        self.retryable = code in RETRYABLE_CODES if retryable is None else retryable
        super().__init__(message)

    @property
    def status_code(self) -> int:
        return ERROR_STATUS[self.code]


def error_body(code: str, message: str, retryable: bool, request_id: str) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "retryable": retryable,
            "request_id": request_id,
        }
    }


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", "-"))


def _validation_message(exc: RequestValidationError) -> str:
    """Field names and reasons only: submitted values (which can be secrets) are never echoed."""
    parts = []
    for item in exc.errors()[:10]:
        location = ".".join(str(p) for p in item.get("loc", ()) if p not in ("body", "query"))
        parts.append(f"{location or 'request'}: {item.get('msg', 'invalid')}")
    return "; ".join(parts) or "invalid request"


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(exc.code, exc.message, exc.retryable, _request_id(request)),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=error_body("invalid_request", _validation_message(exc), False, _request_id(request)),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {
            400: "invalid_request",
            401: "unauthorized",
            403: "forbidden",
            404: "not_found",
            405: "invalid_request",
            409: "conflict_idempotency",
            413: "archive_too_large",
            415: "unsupported_audio",
            422: "invalid_request",
            429: "rate_limited",
        }.get(exc.status_code, "internal" if exc.status_code >= 500 else "invalid_request")
        # Only genuine server-side failures (5xx) and rate limits are worth retrying; a malformed
        # request or a missing route will fail the same way every time.
        retryable = exc.status_code >= 500 or exc.status_code == 429
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(code, str(exc.detail), retryable, _request_id(request)),
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=error_body("internal", "internal server error", True, _request_id(request)),
        )
