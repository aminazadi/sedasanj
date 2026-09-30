from __future__ import annotations

import pytest

from app.errors import ApiError
from app.services import urlguard


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/hook",
        "https://",
        "http://localhost:8000/hook",
        "http://api.local/hook",
    ],
)
def test_rejects_unusable_targets(url: str) -> None:
    with pytest.raises(ApiError):
        urlguard.assert_safe_webhook_url(url)


def test_rejects_private_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        urlguard.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("10.0.0.5", 443))],
    )
    with pytest.raises(ApiError):
        urlguard.assert_safe_webhook_url("https://internal.example.com/hook")


def test_accepts_public_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        urlguard.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("93.184.216.34", 443))],
    )
    urlguard.assert_safe_webhook_url("https://example.com/hook")


async def test_async_wrapper_shares_the_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        urlguard.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("127.0.0.1", 80))],
    )
    with pytest.raises(ApiError):
        await urlguard.assert_safe_webhook_url_async("http://example.com/hook")
