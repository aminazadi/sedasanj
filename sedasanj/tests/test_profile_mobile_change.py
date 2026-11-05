"""Changing the profile mobile needs the password and proof of the new number (WSTG-IDNT)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from app.errors import ApiError
from app.routers import auth, phone_auth
from app.schemas import ProfileUpdate
from app.security import hash_password

PASSWORD = "correct horse battery"


def _user(mobile: str | None = "09121234567") -> Any:
    return SimpleNamespace(id=uuid4(), mobile_number=mobile, password_hash=hash_password(PASSWORD))


def _payload(**overrides: Any) -> ProfileUpdate:
    values: dict[str, Any] = {"display_name": "Ali Reza", "mobile_number": "09121234567"}
    values.update(overrides)
    return ProfileUpdate(**values)


@pytest.fixture()
def spent(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    calls: list[tuple[str, str]] = []

    async def noop(*_args: Any, **_kwargs: Any) -> None:
        return None

    async def fake_consume(_session: Any, token: str, mobile: str) -> None:
        calls.append((token, mobile))

    monkeypatch.setattr(auth.ratelimit, "enforce", noop)
    monkeypatch.setattr(phone_auth, "consume_verified_mobile", fake_consume)
    return calls


@pytest.mark.asyncio
async def test_unchanged_mobile_needs_no_proof(spent: list[tuple[str, str]]) -> None:
    await auth._require_mobile_change_proof(None, _user(), _payload())  # type: ignore[arg-type]
    # Same number written in a different format is still "unchanged".
    await auth._require_mobile_change_proof(  # type: ignore[arg-type]
        None, _user(), _payload(mobile_number="+989121234567")
    )
    assert spent == []


@pytest.mark.asyncio
async def test_changing_mobile_without_password_is_rejected(spent: list[tuple[str, str]]) -> None:
    with pytest.raises(ApiError) as caught:
        await auth._require_mobile_change_proof(  # type: ignore[arg-type]
            None, _user(), _payload(mobile_number="09351112233")
        )
    assert caught.value.code == "current_password_invalid"
    assert spent == []


@pytest.mark.asyncio
async def test_wrong_password_is_rejected(spent: list[tuple[str, str]]) -> None:
    with pytest.raises(ApiError) as caught:
        await auth._require_mobile_change_proof(  # type: ignore[arg-type]
            None,
            _user(),
            _payload(mobile_number="09351112233", current_password="wrong password"),
        )
    assert caught.value.code == "current_password_invalid"


@pytest.mark.asyncio
async def test_new_mobile_needs_a_verified_grant(spent: list[tuple[str, str]]) -> None:
    with pytest.raises(ApiError) as caught:
        await auth._require_mobile_change_proof(  # type: ignore[arg-type]
            None,
            _user(),
            _payload(mobile_number="09351112233", current_password=PASSWORD),
        )
    assert caught.value.code == "mobile_change_verification_required"
    assert spent == []


@pytest.mark.asyncio
async def test_password_plus_grant_allows_change_and_spends_the_grant(
    spent: list[tuple[str, str]],
) -> None:
    token = "t" * 48
    await auth._require_mobile_change_proof(  # type: ignore[arg-type]
        None,
        _user(),
        _payload(
            mobile_number="0935 111 2233",
            current_password=PASSWORD,
            mobile_verified_token=token,
        ),
    )
    assert spent == [(token, "09351112233")]


@pytest.mark.asyncio
async def test_clearing_mobile_needs_password_but_no_grant(spent: list[tuple[str, str]]) -> None:
    await auth._require_mobile_change_proof(  # type: ignore[arg-type]
        None, _user(), _payload(mobile_number=None, current_password=PASSWORD)
    )
    assert spent == []
    with pytest.raises(ApiError):
        await auth._require_mobile_change_proof(  # type: ignore[arg-type]
            None, _user(), _payload(mobile_number=None)
        )
