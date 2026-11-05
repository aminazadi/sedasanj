"""Refresh-token cookie transport for the browser panels (WSTG-SESS-02/04/06).

The panels used to keep the refresh token in localStorage, where any XSS could copy a 14-day
credential. In cookie mode the refresh token travels only in an HttpOnly cookie that scripts
cannot read; the access token stays in JavaScript memory.

Cookie mode is opt-in per request through `X-Auth-Transport: cookie`, so API clients that
store the token themselves (the mobile app) keep working unchanged. The same header guards
CSRF: a cross-site page cannot send a custom header without a CORS preflight that the API
refuses, and the cookie is also `SameSite=Strict` and path-scoped.
"""

from __future__ import annotations

from fastapi import Request, Response

from app.config import get_settings
from app.errors import ApiError
from app.schemas import TokenPair

TRANSPORT_HEADER = "x-auth-transport"
CUSTOMER_COOKIE = "sedasanj_rt"
CUSTOMER_PATH = "/v1/auth"
STAFF_COOKIE = "sedasanj_staff_rt"
STAFF_PATH = "/v1/admin/auth"


def cookie_mode(request: Request) -> bool:
    return request.headers.get(TRANSPORT_HEADER, "").lower() == "cookie"


def _write(response: Response, *, name: str, path: str, value: str, max_age: int) -> None:
    response.set_cookie(
        key=name,
        value=value,
        max_age=max_age,
        path=path,
        secure=get_settings().environment == "production",
        httponly=True,
        samesite="strict",
    )


def deliver_pair(
    request: Request, response: Response, pair: TokenPair, *, name: str, path: str
) -> TokenPair:
    """Return `pair`, moving the refresh token into the cookie when the client asked for it."""
    if not cookie_mode(request):
        return pair
    ttl = get_settings().refresh_token_ttl_days * 86400
    _write(response, name=name, path=path, value=pair.refresh_token, max_age=ttl)
    response.headers["Cache-Control"] = "no-store"
    return pair.model_copy(update={"refresh_token": ""})


def clear_cookie(response: Response, *, name: str, path: str) -> None:
    _write(response, name=name, path=path, value="", max_age=0)


def refresh_token_from(request: Request, body_token: str, *, name: str) -> str:
    """The body token (legacy/mobile) or, in cookie mode, the HttpOnly cookie."""
    if body_token:
        return body_token
    cookie = request.cookies.get(name, "")
    if not cookie or not cookie_mode(request):
        raise ApiError("unauthorized", "refresh token is not usable")
    return cookie
