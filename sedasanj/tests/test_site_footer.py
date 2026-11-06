from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.requests import Request

from app.errors import install_error_handlers
from app.routers.commerce import (
    SiteContactSettingsUpdate,
    admin_site_contact_settings,
    public_site_contact_settings,
    update_site_contact_settings,
)
from app.services.site_footer import FooterLink, FooterSettings


class SettingsSession:
    def __init__(self) -> None:
        self.rows = {}

    async def get(self, model, key):
        return self.rows.get(key)

    def add(self, row):
        self.rows[row.key] = row

    async def flush(self):
        pass


@pytest.mark.parametrize(
    "url",
    ["/about", "/#features", "/help?q=test", "https://example.com/path", "http://example.com"],
)
def test_footer_link_accepts_site_paths_and_web_urls(url):
    assert FooterLink(label="link", url=url).url == url


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "data:text/html,test",
        "//evil.example",
        "/\\evil.example",
        "/\nevil.example",
        "https://user:pass@example.com",
        "https://example.com/a b",
        "https:example.com",
        "about",
    ],
)
def test_footer_link_rejects_unsafe_urls(url):
    with pytest.raises(ValidationError):
        FooterLink(label="link", url=url)


def test_footer_limits_and_empty_groups():
    assert FooterSettings(links=[], legal_links=[]).links == []
    for overrides in [
        {"description": "x" * 4001},
        {"links": [{"label": "", "url": "/"}]},
        {"links": [{"label": "a", "url": "/"}] * 31},
    ]:
        with pytest.raises(ValidationError):
            FooterSettings(**overrides)


def test_footer_refreshes_only_the_legacy_default_copyright():
    expected = "© ۱۴۰۵ صداسنج. تمامی حقوق این وب‌سایت برای صداسنج محفوظ است."
    assert FooterSettings().copyright == expected
    assert FooterSettings(copyright="© ۱۴۰۵ صداسنج").copyright == expected
    assert FooterSettings(copyright="© متن سفارشی").copyright == "© متن سفارشی"


async def test_footer_defaults_save_public_read_and_legacy_update(monkeypatch):
    session = SettingsSession()
    staff = SimpleNamespace(id=uuid4())
    request = Request({"type": "http", "headers": [], "client": ("127.0.0.1", 1234)})
    audit = AsyncMock()
    monkeypatch.setattr("app.routers.commerce.audit.record", audit)
    initial = await public_site_contact_settings(session)
    assert initial["footer"] == FooterSettings().model_dump()
    footer = FooterSettings(
        description="متن جدید", links=[], legal_links=[FooterLink(label="راهنما", url="/help")]
    )
    saved = await update_site_contact_settings(
        SiteContactSettingsUpdate(phone="09399093062", trust_html="badge", footer=footer),
        request,
        staff,
        session,
    )
    assert saved["footer"] == footer.model_dump()
    assert await public_site_contact_settings(session) == saved
    assert await admin_site_contact_settings(staff, session) == saved
    assert audit.call_args.kwargs["payload"]["footer_updated"] is True
    legacy = await update_site_contact_settings(
        SiteContactSettingsUpdate(phone="09399093063", trust_html=""), request, staff, session
    )
    assert legacy["footer"] == footer.model_dump()
    assert legacy["phone"] == "09399093063"
    assert audit.call_args.kwargs["payload"]["footer_updated"] is False


def test_invalid_footer_returns_existing_error_code_without_echoing_url():
    app = FastAPI()
    install_error_handlers(app)

    @app.patch("/settings")
    def update(payload: SiteContactSettingsUpdate):
        return payload

    response = TestClient(app).patch(
        "/settings",
        json={
            "phone": "09399093062",
            "footer": {"links": [{"label": "link", "url": "javascript:private-value"}]},
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"
    assert "private-value" not in response.text


def test_footer_help_migration_is_reversible(monkeypatch):
    import runpy
    from pathlib import Path

    migration_path = (
        Path(__file__).parents[1] / "apps/api/alembic/versions/0088_site_footer_help_content.py"
    )
    migration = runpy.run_path(str(migration_path))
    calls = []
    bind = SimpleNamespace(execute=lambda statement, values: calls.append((str(statement), values)))
    monkeypatch.setattr(migration["op"], "get_bind", lambda: bind)
    migration["upgrade"]()
    migration["downgrade"]()
    assert len(calls) == 2
    assert "INSERT INTO help_articles" in calls[0][0]
    assert "DELETE FROM help_articles" in calls[1][0]
    assert all(values["slug"] == "site-footer-settings-guide" for _, values in calls)
    assert "invalid_request" in calls[0][1]["body"]
    assert all(";" not in statement for statement, _ in calls)
