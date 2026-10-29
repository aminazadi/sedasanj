"""End-to-end smoke test of the help center API against a real PostgreSQL (not part of pytest).

Prepare a throwaway database with the minimal schema (see docs/help-center.md), then:

    DATABASE_URL=postgresql+asyncpg://cbi:x@127.0.0.1:55432/cbi \
        uv run python scripts/smoke_help_center.py
"""

import asyncio
import os
import struct
import zlib

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://cbi:x@127.0.0.1:55432/cbi")
os.environ.update(STORAGE_BACKEND="memory", QUEUE_BACKEND="memory")
import httpx
from sqlalchemy import text

from app import deps
from app.db import get_sessionmaker
from app.deps import Principal
from app.main import create_app


def png() -> bytes:
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))

    raw = b"\x00\xff\x00\x00"
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


async def main():
    async with get_sessionmaker()() as s:
        sid = (
            await s.execute(text("INSERT INTO staff_users DEFAULT VALUES RETURNING id"))
        ).scalar_one()
        await s.commit()
    app = create_app()
    staff = Principal(
        kind="staff", id=sid, tenant_id=None, role="super_admin", mobile_number=None, extension=None
    )

    def ok(cond: bool, msg: str) -> None:
        print(("PASS " if cond else "FAIL ") + msg)
        if not cond:
            raise SystemExit(1)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        # unauthenticated staff access is refused
        r = await c.get("/v1/admin/help/articles")
        ok(r.status_code == 401, f"admin needs auth ({r.status_code})")
        app.dependency_overrides[deps.current_staff] = lambda: staff  # noqa: E731
        r = await c.post("/v1/admin/help/categories", json={"slug": "errors", "title": "خطاها"})
        ok(r.status_code == 201, f"create category {r.status_code} {r.text[:120]}")
        cat = r.json()["id"]
        r = await c.post("/v1/admin/help/categories", json={"slug": "errors", "title": "x"})
        ok(r.status_code == 409, "duplicate category slug -> 409")
        r = await c.post("/v1/admin/help/articles", json={"slug": "Bad Slug", "title": "x"})
        ok(r.status_code == 422, f"bad slug rejected ({r.status_code})")
        body = (
            '<p onclick="x()">کلید API شما رد شد. <script>alert(1)</script></p>'
            '<img src="https://evil.example/x.png"><iframe src="https://evil.example"></iframe>'
        )
        r = await c.post(
            "/v1/admin/help/articles",
            json={
                "slug": "api-key-rejected",
                "title": "کلید API رد شد",
                "summary": "401",
                "body_html": body,
                "kind": "error",
                "category_id": cat,
                "error_codes": ["SS-UPL-0401", "unauthorized"],
            },
        )
        ok(r.status_code == 201, f"create article {r.status_code} {r.text[:200]}")
        art = r.json()
        aid = art["id"]
        ok(
            "script" not in art["body_html"]
            and "onclick" not in art["body_html"]
            and "evil" not in art["body_html"],
            "stored HTML is sanitized",
        )
        ok(sorted(art["error_codes"]) == ["SS-UPL-0401", "unauthorized"], "error codes linked")
        r = await c.get("/v1/help/articles/api-key-rejected")
        ok(r.status_code == 404, "draft is not public")
        r = await c.get("/v1/help/errors/SS-UPL-0401")
        ok(
            r.status_code == 200 and r.json()["article_published"] is False,
            "code resolves but article unpublished",
        )
        r = await c.post(f"/v1/admin/help/articles/{aid}/publish")
        ok(r.status_code == 200 and r.json()["status"] == "published", "publish")
        r = await c.get("/v1/help/articles/api-key-rejected")
        ok(
            r.status_code == 200 and r.json()["title"] == "کلید API رد شد",
            "published article is public",
        )
        r = await c.get("/v1/help/errors/ss-upl-0401")
        j = r.json()
        ok(
            r.status_code == 200 and j["article_slug"] == "api-key-rejected",
            f"deep link, case-insensitive: {j}",
        )
        r = await c.get("/v1/help/errors/nope-code")
        ok(r.status_code == 404, "unknown code 404")
        r = await c.get("/v1/help/articles", params={"q": "رد شد"})
        ok(r.status_code == 200 and r.json()["total"] == 1, f"Persian search {r.json()}")
        r = await c.get("/v1/help/articles", params={"q": "zzzzzz"})
        ok(r.json()["total"] == 0, "search miss")
        r = await c.get("/v1/help/articles", params={"q": "100%_"})
        ok(r.status_code == 200, "LIKE wildcards are escaped")
        r = await c.get("/v1/help/categories")
        ok(r.json()[0]["article_count"] == 1, "category article count")
        # media
        r = await c.post(
            "/v1/admin/help/media",
            files={"file": ("shot.png", png(), "image/png")},
            data={"alt": "شکل"},
        )
        ok(r.status_code == 201, f"upload png {r.status_code} {r.text[:150]}")
        m = r.json()
        r = await c.get(m["url"])
        ok(
            r.status_code == 200
            and r.content[:4] == b"\x89PNG"
            and r.headers["x-content-type-options"] == "nosniff",
            "public media served with nosniff",
        )
        r = await c.post(
            "/v1/admin/help/media",
            files={"file": ("x.png", b'<svg onload="x()"></svg>', "image/png")},
        )
        ok(r.status_code == 422, f"SVG disguised as PNG refused ({r.status_code})")
        r = await c.patch(
            f"/v1/admin/help/articles/{aid}",
            json={
                "body_html": f'<p>نگاه کنید</p><figure><img src="{m["url"]}" alt="شکل"></figure>'
            },
        )
        ok(m["url"] in r.json()["body_html"], "platform image kept in body")
        r = await c.delete(f"/v1/admin/help/media/{m['id']}")
        ok(r.status_code == 409, "media in use cannot be deleted")
        # catalog seeding
        r = await c.post("/v1/admin/help/error-codes/seed-module")
        ok(r.status_code == 200 and r.json()["created"] >= 70, f"seed {r.json()}")
        r = await c.post("/v1/admin/help/error-codes/seed-module")
        ok(r.json()["created"] == 0, "seeding is idempotent")
        r = await c.get("/v1/help/errors/SS-UPL-0401")
        ok(
            r.json()["article_slug"] == "api-key-rejected" and r.json()["title"],
            "seed kept the article link and filled the title",
        )
        r = await c.get("/v1/admin/help/error-codes", params={"only_missing": "true"})
        ok(len(r.json()) >= 70, f"codes still lacking a published article: {len(r.json())}")
        r = await c.delete(f"/v1/admin/help/articles/{aid}")
        ok(r.status_code == 204, "delete article")
        r = await c.get("/v1/help/errors/SS-UPL-0401")
        ok(
            r.status_code == 200 and r.json()["article_slug"] is None,
            "code survives article deletion",
        )
        n = (
            await (await get_sessionmaker()().__aenter__()).execute(
                text("SELECT count(*) FROM audit_events WHERE action LIKE 'help_%'")
            )
        ).scalar_one()
        ok(n >= 8, f"audit trail written ({n} events)")


asyncio.run(main())
