"""Refresh tokens travel in an HttpOnly cookie for the browser panels (WSTG-SESS-02/04/06)."""

from __future__ import annotations

import pytest
from starlette.requests import Request
from starlette.responses import Response

from app.errors import ApiError
from app.schemas import TokenPair
from app.services import auth_cookies

PAIR = TokenPair(access_token="access.jwt.value", refresh_token="r" * 64, expires_in=900)


def _request(headers: dict[str, str] | None = None, cookie: str | None = None) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    if cookie is not None:
        raw.append((b"cookie", cookie.encode()))
    return Request({"type": "http", "method": "POST", "path": "/", "headers": raw})


def _set_cookie(response: Response) -> str:
    return response.headers.get("set-cookie", "")


def test_cookie_mode_moves_refresh_token_into_httponly_cookie() -> None:
    response = Response()
    request = _request({"x-auth-transport": "cookie"})
    out = auth_cookies.deliver_pair(
        request, response, PAIR, name=auth_cookies.CUSTOMER_COOKIE, path=auth_cookies.CUSTOMER_PATH
    )
    assert out.refresh_token == ""
    assert out.access_token == PAIR.access_token
    cookie = _set_cookie(response)
    assert f"{auth_cookies.CUSTOMER_COOKIE}={PAIR.refresh_token}" in cookie
    lowered = cookie.lower()
    assert "httponly" in lowered
    assert "samesite=strict" in lowered
    assert "path=/v1/auth" in lowered
    assert response.headers["cache-control"] == "no-store"


def test_cookie_is_secure_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Settings:
        environment = "production"
        refresh_token_ttl_days = 14

    monkeypatch.setattr(auth_cookies, "get_settings", lambda: _Settings())
    response = Response()
    auth_cookies.deliver_pair(
        _request({"x-auth-transport": "cookie"}),
        response,
        PAIR,
        name=auth_cookies.STAFF_COOKIE,
        path=auth_cookies.STAFF_PATH,
    )
    assert "secure" in _set_cookie(response).lower()


def test_without_the_header_the_pair_is_returned_unchanged() -> None:
    response = Response()
    out = auth_cookies.deliver_pair(
        _request(), response, PAIR, name=auth_cookies.CUSTOMER_COOKIE, path="/v1/auth"
    )
    assert out == PAIR
    assert _set_cookie(response) == ""


def test_body_token_still_works_for_non_browser_clients() -> None:
    token = auth_cookies.refresh_token_from(_request(), "legacy-token", name="sedasanj_rt")
    assert token == "legacy-token"


def test_cookie_token_requires_the_transport_header() -> None:
    cookie = "sedasanj_rt=" + "c" * 40
    with pytest.raises(ApiError) as caught:
        auth_cookies.refresh_token_from(_request(cookie=cookie), "", name="sedasanj_rt")
    assert caught.value.code == "unauthorized"
    ok = auth_cookies.refresh_token_from(
        _request({"x-auth-transport": "cookie"}, cookie), "", name="sedasanj_rt"
    )
    assert ok == "c" * 40


def test_missing_token_everywhere_is_unauthorized() -> None:
    with pytest.raises(ApiError):
        auth_cookies.refresh_token_from(
            _request({"x-auth-transport": "cookie"}), "", name="sedasanj_rt"
        )


def test_clear_cookie_expires_it() -> None:
    response = Response()
    auth_cookies.clear_cookie(response, name="sedasanj_rt", path="/v1/auth")
    cookie = _set_cookie(response).lower()
    assert "max-age=0" in cookie
    assert "httponly" in cookie


def test_staff_and_customer_cookies_do_not_collide() -> None:
    assert auth_cookies.STAFF_COOKIE != auth_cookies.CUSTOMER_COOKIE
    assert auth_cookies.STAFF_PATH.startswith("/v1/admin/")
    assert not auth_cookies.CUSTOMER_PATH.startswith("/v1/admin")
