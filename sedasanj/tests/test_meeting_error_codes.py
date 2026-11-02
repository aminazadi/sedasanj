"""The eleven meeting error codes: status, retry semantics and body shape."""

from __future__ import annotations

import ast
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from app.errors import ERROR_STATUS, RETRYABLE_CODES, ApiError, install_error_handlers

MEETING_CODES = {
    "meeting_not_found": 404,
    "meeting_closed": 409,
    "meeting_chunk_conflict": 409,
    "meeting_incomplete_chunks": 409,
    "meeting_chunk_too_large": 413,
    "meeting_chunk_invalid_audio": 422,
    "meeting_token_limit": 409,
    "meeting_pairing_invalid": 400,
    "meeting_asr_failed": 502,
    "meeting_diarization_failed": 502,
    "meeting_minutes_failed": 502,
}


@pytest.mark.parametrize(("code", "http_status"), sorted(MEETING_CODES.items()))
def test_each_meeting_code_has_its_http_status(code: str, http_status: int) -> None:
    assert ERROR_STATUS[code] == http_status
    assert ApiError(code, "message").status_code == http_status


def test_only_transient_processing_failures_are_retryable() -> None:
    retryable = {code for code in MEETING_CODES if code in RETRYABLE_CODES}
    assert retryable == {"meeting_asr_failed", "meeting_minutes_failed"}


def test_every_code_raised_by_the_meeting_code_is_declared() -> None:
    root = Path(__file__).resolve().parents[1] / "apps/api/app"
    raised: set[str] = set()
    for path in (
        root / "routers/meetings.py",
        root / "services/meeting_ingest.py",
        root / "services/billing.py",
        root / "deps.py",
    ):
        for node in ast.walk(ast.parse(path.read_text())):
            if (
                isinstance(node, ast.Call)
                and getattr(node.func, "id", None) == "ApiError"
                and node.args
                and isinstance(node.args[0], ast.Constant)
            ):
                raised.add(str(node.args[0].value))
    assert {code for code in raised if code.startswith("meeting_")} <= set(MEETING_CODES)
    assert raised <= set(ERROR_STATUS)


async def test_extra_detail_is_merged_into_the_error_body() -> None:
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/x")
    async def x() -> None:
        raise ApiError(
            "meeting_incomplete_chunks", "send them again", extra={"missing_seqs": [1, 4]}
        )

    @app.get("/y")
    async def y() -> None:
        raise ApiError("meeting_closed", "closed", extra={"code": "spoofed"})

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as client:
        body = (await client.get("/x")).json()["error"]
        assert body["missing_seqs"] == [1, 4] and body["code"] == "meeting_incomplete_chunks"
        assert (await client.get("/y")).json()["error"]["code"] == "meeting_closed"
