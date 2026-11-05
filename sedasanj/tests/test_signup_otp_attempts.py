"""Signup OTP: failed attempts must be committed, and the cap must hold (WSTG-ATHN-03)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from app import security
from app.errors import ApiError
from app.routers import commerce


class _Scope:
    """Fake control session that records whether the scope exited cleanly (= commit)."""

    def __init__(self, row: Any) -> None:
        self.row = row
        self.committed = False

    @asynccontextmanager
    async def __call__(self):  # type: ignore[no-untyped-def]
        scope = self

        class _Session:
            async def get(self, *_args: Any, **_kwargs: Any) -> Any:
                return scope.row

        yield _Session()
        # Reached only when the body did not raise, i.e. the real scope would commit.
        self.committed = True


def _row(**overrides: Any) -> Any:
    values: dict[str, Any] = {
        "id": uuid4(),
        "code_hash": "hash",
        "attempts": 0,
        "expires_at": datetime.now(UTC) + timedelta(minutes=2),
        "verified_at": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _request() -> Any:
    return SimpleNamespace(headers={}, client=SimpleNamespace(host="203.0.113.7"))


@pytest.fixture()
def patched(monkeypatch: pytest.MonkeyPatch):
    async def noop(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(commerce.ratelimit, "enforce", noop)
    monkeypatch.setattr(commerce.audit, "record", noop)
    return monkeypatch


@pytest.mark.asyncio
async def test_wrong_code_commits_attempt_before_raising(patched: pytest.MonkeyPatch) -> None:
    patched.setattr(security, "verify_password", lambda _hash, _code: False)
    row = _row()
    scope = _Scope(row)
    patched.setattr(commerce, "control_session_scope", scope)
    with pytest.raises(ApiError) as caught:
        await commerce.verify_signup_otp(
            commerce.OtpVerify(otp_id=row.id, code="000000"), _request()
        )
    assert caught.value.code == "unauthorized"
    assert row.attempts == 1
    assert scope.committed is True, "the attempt counter must be committed before the error"


@pytest.mark.asyncio
async def test_attempt_cap_blocks_even_the_correct_code(patched: pytest.MonkeyPatch) -> None:
    patched.setattr(security, "verify_password", lambda _hash, _code: True)
    row = _row(attempts=commerce.SIGNUP_OTP_MAX_ATTEMPTS)
    patched.setattr(commerce, "control_session_scope", _Scope(row))
    with pytest.raises(ApiError):
        await commerce.verify_signup_otp(
            commerce.OtpVerify(otp_id=row.id, code="123456"), _request()
        )
    assert row.verified_at is None


@pytest.mark.asyncio
async def test_correct_code_marks_verified(patched: pytest.MonkeyPatch) -> None:
    patched.setattr(security, "verify_password", lambda _hash, _code: True)
    row = _row()
    patched.setattr(commerce, "control_session_scope", _Scope(row))
    result = await commerce.verify_signup_otp(
        commerce.OtpVerify(otp_id=row.id, code="123456"), _request()
    )
    assert result == {"verified": True}
    assert row.verified_at is not None


@pytest.mark.asyncio
async def test_already_verified_or_expired_code_is_rejected(patched: pytest.MonkeyPatch) -> None:
    patched.setattr(security, "verify_password", lambda _hash, _code: True)
    for row in (
        _row(verified_at=datetime.now(UTC)),
        _row(expires_at=datetime.now(UTC) - timedelta(seconds=1)),
    ):
        patched.setattr(commerce, "control_session_scope", _Scope(row))
        with pytest.raises(ApiError):
            await commerce.verify_signup_otp(
                commerce.OtpVerify(otp_id=row.id, code="123456"), _request()
            )
