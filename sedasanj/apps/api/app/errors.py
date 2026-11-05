from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

ERROR_STATUS: dict[str, int] = {
    "login_mobile_ambiguous": status.HTTP_409_CONFLICT,
    "password_change_mobile_required": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "password_change_verification_required": status.HTTP_400_BAD_REQUEST,
    "password_change_totp_required": status.HTTP_400_BAD_REQUEST,
    "org_archive_invalid": 422,
    "org_archive_too_large": 413,
    "org_archive_mapping": 422,
    "org_archive_review_changed": 409,
    "org_archive_unavailable": 503,
    "org_backup_destination": 422,
    "org_backup_ftp_failed": 502,
    "jalase_negar_release_not_found": status.HTTP_404_NOT_FOUND,
    "meeting_not_found": status.HTTP_404_NOT_FOUND,
    "meeting_closed": status.HTTP_409_CONFLICT,
    "meeting_chunk_conflict": status.HTTP_409_CONFLICT,
    "meeting_incomplete_chunks": status.HTTP_409_CONFLICT,
    "meeting_chunk_too_large": status.HTTP_413_CONTENT_TOO_LARGE,
    "meeting_chunk_invalid_audio": 422,
    "meeting_token_limit": status.HTTP_409_CONFLICT,
    "meeting_pairing_invalid": status.HTTP_400_BAD_REQUEST,
    "meeting_asr_failed": status.HTTP_502_BAD_GATEWAY,
    "meeting_diarization_failed": status.HTTP_502_BAD_GATEWAY,
    "meeting_minutes_failed": status.HTTP_502_BAD_GATEWAY,
    "meeting_transcript_missing": status.HTTP_409_CONFLICT,
    "meeting_transcript_invalid": 422,
    "speaker_profile_not_found": status.HTTP_404_NOT_FOUND,
    "speaker_profile_conflict": status.HTTP_409_CONFLICT,
    "speaker_profile_limit": status.HTTP_409_CONFLICT,
    "speaker_consent_required": 422,
    "speaker_voiceprint_invalid": 422,
    "speaker_storage_unavailable": status.HTTP_503_SERVICE_UNAVAILABLE,
    "tenant_instructions_too_long": 422,
    "apk_invalid": 422,
    "apk_inspection_unavailable": status.HTTP_503_SERVICE_UNAVAILABLE,
    "release_version_conflict": status.HTTP_409_CONFLICT,
    "release_file_unavailable": status.HTTP_503_SERVICE_UNAVAILABLE,
    "update_checksum_mismatch": 422,
    "update_downgrade_rejected": 422,
    "update_install_blocked": 422,
    "task_version_conflict": 409,
    "task_assignee_invalid": 422,
    "unauthorized": status.HTTP_401_UNAUTHORIZED,
    "forbidden": status.HTTP_403_FORBIDDEN,
    "insufficient_credit": status.HTTP_402_PAYMENT_REQUIRED,
    "quota_exceeded": status.HTTP_402_PAYMENT_REQUIRED,
    "subscription_inactive": status.HTTP_402_PAYMENT_REQUIRED,
    "tenant_suspended": status.HTTP_403_FORBIDDEN,
    "api_key_scope_denied": status.HTTP_403_FORBIDDEN,
    "api_key_expired": status.HTTP_401_UNAUTHORIZED,
    "ip_not_allowed": status.HTTP_403_FORBIDDEN,
    "conflict_idempotency": status.HTTP_409_CONFLICT,
    "unsupported_audio": status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
    "unsupported_archive": status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
    "archive_password_required": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "archive_password_invalid": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "archive_unsafe": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "archive_too_large": status.HTTP_413_CONTENT_TOO_LARGE,
    "asr_no_speech": 422,
    "call_asr_settings_invalid": 422,
    "call_retranscription_busy": 409,
    "not_found": status.HTTP_404_NOT_FOUND,
    "rate_limited": status.HTTP_429_TOO_MANY_REQUESTS,
    "invalid_request": 422,
    "assistant_tool_disabled": 422,
    "assistant_tool_plan_invalid": 422,
    "assistant_export_unavailable": 503,
    "coach_unavailable": status.HTTP_409_CONFLICT,
    "export_expired": 410,
    "export_too_large": 422,
    "document_not_ready": status.HTTP_409_CONFLICT,
    "document_pdf_unavailable": status.HTTP_503_SERVICE_UNAVAILABLE,
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
    "meeting_asr_failed",
    "meeting_minutes_failed",
    "document_pdf_unavailable",
    "release_file_unavailable",
    "apk_inspection_unavailable",
    "speaker_storage_unavailable",
}


class ApiError(Exception):
    """Error carrying one of the §7.3 codes."""

    def __init__(
        self,
        code: str,
        message: str,
        retryable: bool | None = None,
        retry_after: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        if code not in ERROR_STATUS:
            raise ValueError(f"unknown error code {code}")
        self.code = code
        self.retry_after = retry_after
        self.message = message
        # Machine-readable detail merged into the error body (for example `missing_seqs`).
        self.extra = extra or {}
        self.retryable = code in RETRYABLE_CODES if retryable is None else retryable
        super().__init__(message)

    @property
    def status_code(self) -> int:
        return ERROR_STATUS[self.code]


def error_body(
    code: str,
    message: str,
    retryable: bool,
    request_id: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "error": {
            **(extra or {}),
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
            content=error_body(
                exc.code, exc.message, exc.retryable, _request_id(request), exc.extra
            ),
            headers={"Retry-After": str(exc.retry_after)} if exc.retry_after else None,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=error_body(
                "invalid_request", _validation_message(exc), False, _request_id(request)
            ),
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
