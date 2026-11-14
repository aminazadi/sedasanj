"""Jalase-Negar download dialog: store links and Windows/macOS installers.

Pure tests run everywhere. API tests need JALASE_NEGAR_TEST_DSN (a disposable database whose
name contains "test" or "scratch"), as in test_jalase_negar_releases.py.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from uuid import uuid4

import httpx
import pytest

from app.errors import ApiError
from app.services import jalase_negar_downloads as dl

TEST_DSN = os.environ.get("JALASE_NEGAR_TEST_DSN")
needs_database = pytest.mark.skipif(not TEST_DSN, reason="JALASE_NEGAR_TEST_DSN is not set")


def test_upload_validation_builds_safe_names() -> None:
    assert dl.validate_upload("windows", "1.2.0", "Setup.EXE") == (
        "1.2.0",
        "jalase-negar-windows-1.2.0.exe",
    )
    assert dl.validate_upload("macos", "2.0", "x.dmg")[1] == "jalase-negar-macos-2.0.dmg"


@pytest.mark.parametrize(
    ("platform", "version", "name"),
    [
        ("linux", "1.0", "a.exe"),
        ("windows", "1.0", "a.dmg"),
        ("macos", "1.0", "a.exe"),
        ("windows", "../1", "a.exe"),
        ("windows", "", "a.exe"),
    ],
)
def test_upload_validation_rejects(platform: str, version: str, name: str) -> None:
    with pytest.raises(ApiError) as caught:
        dl.validate_upload(platform, version, name)
    assert caught.value.code == "invalid_request"


def test_store_links_accept_only_https() -> None:
    assert dl.StoreLinks(bazaar="https://cafebazaar.ir/app/x").bazaar.startswith("https://")
    assert dl.StoreLinks().myket == ""
    for bad in ("http://a.ir", "javascript:alert(1)", "https://a.ir/x y"):
        with pytest.raises(ValueError):
            dl.StoreLinks(myket=bad)


class Env:
    def __init__(self, client: httpx.AsyncClient, admin: dict[str, str], support: dict[str, str]):
        self.client, self.admin, self.support = client, admin, support

    async def upload(self, platform: str, version: str, name: str, body: bytes = b"binary-data"):
        return await self.client.post(
            "/v1/admin/jalase-negar/desktop-builds",
            files={"file": (name, body)},
            data={"platform": platform, "version": version},
            headers=self.admin,
        )


@pytest.fixture()
async def env(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Env]:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from app import db
    from app.config import get_settings
    from app.models import (
        AuditEvent,
        Base,
        JalaseNegarDesktopBuild,
        JalaseNegarRelease,
        PlatformSetting,
        StaffUser,
    )
    from app.security import create_access_token, hash_password
    from app.services import ratelimit
    from app.services.storage import MemoryStorage, set_storage

    assert TEST_DSN
    database = TEST_DSN.rsplit("/", 1)[-1]
    assert "test" in database or "scratch" in database, "refusing to run on a non-test database"
    monkeypatch.setenv("DATABASE_URL", TEST_DSN)
    monkeypatch.setenv("QUEUE_BACKEND", "memory")
    monkeypatch.setenv("TENANT_DATABASES_ENABLED", "false")
    get_settings.cache_clear()
    await db.dispose_engine()
    ratelimit._memory.clear()
    tables = [
        StaffUser.__table__,
        AuditEvent.__table__,
        JalaseNegarRelease.__table__,
        JalaseNegarDesktopBuild.__table__,
        PlatformSetting.__table__,
    ]
    engine = create_async_engine(TEST_DSN)
    async with engine.begin() as connection:
        await connection.run_sync(lambda sync: Base.metadata.drop_all(sync, tables=tables))
        await connection.run_sync(lambda sync: Base.metadata.create_all(sync, tables=tables))
    await engine.dispose()
    set_storage(MemoryStorage())

    from app.main import create_app

    transport = httpx.ASGITransport(app=create_app(), client=("203.0.113.9", 4000))
    async with httpx.AsyncClient(transport=transport, base_url="http://api") as client:
        headers: dict[str, dict[str, str]] = {}
        async with db.session_scope(staff=True) as session:
            users = {
                role: StaffUser(
                    email=f"{role}{uuid4().hex[:6]}@example.com",
                    password_hash=hash_password("x" * 12),
                    role=role,
                )
                for role in ("super_admin", "support")
            }
            session.add_all(users.values())
            await session.flush()
            for role, user in users.items():
                token = create_access_token(
                    subject=user.id, tenant_id=None, role=role, actor="staff"
                )
                headers[role] = {"Authorization": f"Bearer {token}"}
        yield Env(client, headers["super_admin"], headers["support"])
    set_storage(None)
    await db.dispose_engine()
    async with create_async_engine(TEST_DSN).begin() as connection:
        for table in ("jalase_negar_desktop_builds", "jalase_negar_releases", "platform_settings"):
            await connection.execute(text(f"DROP TABLE IF EXISTS {table}"))
    get_settings.cache_clear()


@needs_database
async def test_overview_is_empty_then_lists_builds_and_links(env: Env) -> None:
    empty = (await env.client.get("/v1/jalase-negar/downloads")).json()
    assert empty == {"android": None, "windows": None, "macos": None, "stores": {}}

    assert (await env.upload("windows", "1.0.0", "setup.exe")).status_code == 201
    newest = (await env.upload("windows", "1.1.0", "setup.exe", b"newer")).json()
    assert (await env.upload("macos", "1.1.0", "app.dmg")).status_code == 201
    saved = await env.client.put(
        "/v1/admin/jalase-negar/store-links",
        json={"bazaar": "https://cafebazaar.ir/app/x", "sibapp": "https://sibapp.com/x"},
        headers=env.admin,
    )
    assert saved.status_code == 200

    overview = await env.client.get("/v1/jalase-negar/downloads")
    body = overview.json()
    assert overview.headers["cache-control"] == "no-store"
    assert body["windows"]["version"] == "1.1.0"
    assert body["windows"]["download_path"].endswith(f"/{newest['id']}/download")
    assert body["macos"]["version"] == "1.1.0"
    assert body["stores"] == {
        "bazaar": "https://cafebazaar.ir/app/x",
        "sibapp": "https://sibapp.com/x",
    }

    file = await env.client.get(body["windows"]["download_path"])
    assert file.status_code == 200 and file.content == b"newer"
    assert "jalase-negar-windows-1.1.0.exe" in file.headers["content-disposition"]


@needs_database
async def test_staff_rules_and_validation(env: Env) -> None:
    denied = await env.client.post(
        "/v1/admin/jalase-negar/desktop-builds",
        files={"file": ("a.exe", b"x")},
        data={"platform": "windows", "version": "1.0"},
        headers=env.support,
    )
    assert denied.status_code == 403
    assert (await env.upload("windows", "1.0", "a.dmg")).status_code == 422
    assert (await env.upload("windows", "1.0", "a.exe", b"")).status_code == 422
    bad = await env.client.put(
        "/v1/admin/jalase-negar/store-links", json={"myket": "http://x.ir"}, headers=env.admin
    )
    assert bad.status_code == 422


@needs_database
async def test_delete_removes_build_and_file(env: Env) -> None:
    build = (await env.upload("macos", "3.0", "a.pkg")).json()
    path = f"/v1/admin/jalase-negar/desktop-builds/{build['id']}"
    assert (await env.client.delete(path, headers=env.admin)).status_code == 204
    assert (await env.client.delete(path, headers=env.admin)).status_code == 404
    gone = await env.client.get(f"/v1/jalase-negar/desktop/{build['id']}/download")
    assert gone.status_code == 404
