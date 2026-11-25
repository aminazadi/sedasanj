"""Public Jalase-Negar catalogue: no sign-in, stable ETag, 304 on a matching If-None-Match."""

from starlette.requests import Request

from app.routers import jalase_catalog


def _request(headers: dict[str, str] | None = None) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request({"type": "http", "method": "GET", "path": "/", "headers": raw})


def test_catalog_routes_take_no_principal():
    """The catalogue is public: none of its routes may depend on an API key or user."""
    for route in jalase_catalog.router.routes:
        dependant_names = {d.call.__name__ for d in route.dependant.dependencies}  # type: ignore[attr-defined]
        assert not dependant_names & {"current_api_key", "current_user", "require_mobile_scope"}


def test_respond_returns_etag_and_body():
    response = jalase_catalog._respond(_request(), {"items": [{"code": "minutes"}]})
    assert response.status_code == 200
    assert response.headers["etag"].startswith('"')
    assert response.headers["cache-control"] == jalase_catalog.CACHE_CONTROL
    assert b"minutes" in response.body


def test_respond_returns_304_when_etag_matches():
    first = jalase_catalog._respond(_request(), {"items": []})
    second = jalase_catalog._respond(
        _request({"If-None-Match": first.headers["etag"]}), {"items": []}
    )
    assert second.status_code == 304
    assert second.body == b""
