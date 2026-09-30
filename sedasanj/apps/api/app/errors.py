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
    "internal": status.HTTP_500_INTERNAL_SERVER_ERROR,
}

RETRYABLE_CODES = {"insufficient_credit", "quota_exceeded", "rate_limited", "internal"}


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
            content=error_body("invalid_request", str(exc.errors()), False, _request_id(request)),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {
            401: "unauthorized",
            403: "forbidden",
            404: "not_found",
            409: "conflict_idempotency",
            415: "unsupported_audio",
            429: "rate_limited",
        }.get(exc.status_code, "internal")
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(
                code, str(exc.detail), code in RETRYABLE_CODES, _request_id(request)
            ),
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=error_body("internal", "internal server error", True, _request_id(request)),
        )
