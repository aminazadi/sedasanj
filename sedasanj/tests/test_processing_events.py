from __future__ import annotations

from app.services.processing_events import sanitize_detail


def test_sanitize_detail_redacts_common_secret_formats() -> None:
    detail = (
        "Authorization: Bearer bearer-value "
        "api_key=plain-value "
        "https://user:password@example.test/path "
        "https://example.test/callback?access_token=query-value&ok=1"
    )

    sanitized = sanitize_detail(detail)

    assert sanitized is not None
    assert "bearer-value" not in sanitized
    assert "plain-value" not in sanitized
    assert "password" not in sanitized
    assert "query-value" not in sanitized
    assert sanitized.count("[REDACTED]") == 4


def test_sanitize_detail_removes_nuls_and_applies_public_limit() -> None:
    sanitized = sanitize_detail("failure\x00detail" + "x" * 50, limit=20)

    assert sanitized == "failure detailxxxxxx"
    assert len(sanitized) == 20
