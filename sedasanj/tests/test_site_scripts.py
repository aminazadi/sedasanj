from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import Response

from app.errors import ApiError
from app.routers import site_scripts as routes
from app.services.site_scripts import ScriptSlots, SiteScripts, parse_scripts, version


@pytest.mark.parametrize(
    "value",
    [
        '<script src="javascript:alert(1)"></script>',
        '<script src="//example.com/a.js"></script>',
        '<script src="http://example.com/a.js"></script>',
        '<script src="https://user:pass@example.com/a.js"></script>',
        "<img src=x onerror=alert(1)>",
        '<script onload="alert(1)"></script>',
        "<script>unfinished",
        "<script />",
        "alert(1)",
        "<script></script>" * 31,
    ],
)
def test_invalid_snippets_have_actionable_error(value):
    with pytest.raises(ApiError) as error:
        parse_scripts(value)
    assert error.value.code == "site_scripts_invalid"
    assert "save again" in error.value.message


def test_scripts_preserve_code_and_attributes_in_order():
    scripts = parse_scripts(
        '<script>window.example = "<&";</script>'
        '<script async src="https://example.com/a.js"></script>'
    )
    assert scripts[0]["code"] == 'window.example = "<&";'
    assert scripts[1]["src"] == "https://example.com/a.js"
    assert "async" in scripts[1]
    assert parse_scripts("") == []


class SettingsSession:
    def __init__(self):
        self.rows = {}

    async def get(self, model, key):
        return self.rows.get(key)

    def add(self, row):
        self.rows[row.key] = row

    async def flush(self):
        pass


@pytest.mark.asyncio
async def test_save_manifest_and_script_delivery_are_scoped_and_audited(monkeypatch):
    session = SettingsSession()
    verify = AsyncMock()
    audit = AsyncMock()
    monkeypatch.setattr(routes, "_verify_sensitive_staff_action", verify)
    monkeypatch.setattr(routes.audit, "record", audit)
    monkeypatch.setattr(routes, "client_ip", lambda request: "127.0.0.1")
    code = "window.publicOnly = true;"
    payload = routes.ScriptsUpdate(
        public=ScriptSlots(head=f"<script>{code}</script>"),
        customer=ScriptSlots(body='<script src="https://example.com/customer.js"></script>'),
        current_password="not-logged",
    )
    saved = await routes.save_scripts(payload, None, SimpleNamespace(id="staff"), session)
    verify.assert_awaited_once()
    assert "not-logged" not in session.rows["site_scripts"].value
    assert audit.call_args.kwargs["payload"] == {"updated": True}
    response = Response()
    manifest = await routes.script_manifest("public", session, response)
    assert manifest["body"] == []
    assert manifest["head"][0]["src"].endswith(f"/{version(code)}.js")
    assert "code" not in manifest["head"][0]
    assert response.headers["cache-control"] == "no-store"
    delivered = await routes.inline_script("public", "head", 0, version(code), session)
    assert delivered.body.decode() == code
    assert delivered.media_type == "text/javascript"
    with pytest.raises(ApiError):
        await routes.inline_script("customer", "head", 0, version(code), session)
    with pytest.raises(ApiError):
        await routes.inline_script("public", "head", -1, version(code), session)
    with pytest.raises(ApiError):
        await routes.inline_script("public", "head", 0, "stale", session)
    cleared = await routes.save_scripts(
        routes.ScriptsUpdate(current_password="not-logged"),
        None,
        SimpleNamespace(id="staff"),
        session,
    )
    assert cleared == SiteScripts()
    assert saved.public.head


@pytest.mark.parametrize("role", ["support", "admin", "org_admin", "operator"])
def test_non_super_admin_cannot_read_or_write_scripts(role):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.deps import current_staff, staff_session
    from app.errors import install_error_handlers

    app = FastAPI()
    app.include_router(routes.router)
    install_error_handlers(app)
    app.dependency_overrides[current_staff] = lambda: SimpleNamespace(id="staff", role=role)
    app.dependency_overrides[staff_session] = lambda: SettingsSession()
    with TestClient(app) as client:
        assert client.get("/v1/admin/site-scripts").status_code == 403
        assert (
            client.put("/v1/admin/site-scripts", json={"current_password": "test"}).status_code
            == 403
        )
