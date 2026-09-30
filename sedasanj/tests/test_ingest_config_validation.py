from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.errors import ApiError
from app.routers.ingest import _validate_archive_password
from app.security import hash_password


async def test_config_validation_accepts_matching_zip_password() -> None:
    key = SimpleNamespace(archive_password_hash=hash_password("Strong-Passphrase-2026"))
    assert await _validate_archive_password(key, "Strong-Passphrase-2026") is True


async def test_config_validation_rejects_missing_zip_password() -> None:
    key = SimpleNamespace(archive_password_hash=hash_password("Strong-Passphrase-2026"))
    with pytest.raises(ApiError) as caught:
        await _validate_archive_password(key, None)
    assert caught.value.code == "archive_password_required"


async def test_config_validation_rejects_password_for_unprotected_key() -> None:
    key = SimpleNamespace(archive_password_hash=None)
    with pytest.raises(ApiError) as caught:
        await _validate_archive_password(key, "unexpected")
    assert caught.value.code == "archive_password_invalid"


def test_credit_errors_are_retryable() -> None:
    assert ApiError("insufficient_credit", "top up required").retryable is True
    assert ApiError("quota_exceeded", "upgrade required").retryable is True
