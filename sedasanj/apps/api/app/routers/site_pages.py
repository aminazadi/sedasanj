"""Editable public pages (about, contact, terms, privacy, cancellation)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Path, Request, status
from pydantic import ValidationError

from app.deps import PublicSession, StaffDep, StaffSession, client_ip
from app.errors import ApiError
from app.models import HelpMedia, PlatformSetting
from app.services import audit, ratelimit, site_pages

router = APIRouter(prefix="/v1", tags=["site-pages"])

Slug = Annotated[
    str, Path(pattern="^(about|contact|terms|privacy|cancellation|landing_video|auth_aside)$")
]


def _problem(error: ValidationError) -> str:
    """Field paths only: the offending values are never echoed back."""
    paths = sorted({".".join(str(part) for part in item["loc"]) for item in error.errors()})
    return "invalid page content: " + ", ".join(paths[:8])


async def _view(session: Any, slug: str) -> dict[str, Any]:
    row = await session.get(PlatformSetting, site_pages.setting_key(slug))
    content, is_default = site_pages.load_content(slug, row.value if row else None)
    return {
        "slug": slug,
        "content": content,
        "is_default": is_default,
        "updated_at": row.updated_at if row else None,
    }


async def _check_media(session: Any, content: dict[str, Any]) -> None:
    """The avatar must be an uploaded image; the intro and every answer an uploaded video."""
    checks = [("avatar_media_id", content["avatar_media_id"], "image")]
    checks.append(("video_media_id", content["video_media_id"], "video"))
    for index, item in enumerate(content["questions"]):
        checks.append((f"questions.{index}.video_media_id", item["video_media_id"], "video"))
    for field, media_id, kind in checks:
        if not media_id:
            continue
        media = await session.get(HelpMedia, UUID(media_id))
        if media is None or media.kind != kind:
            raise ApiError(
                "invalid_request",
                f"{field} must be an uploaded {kind} file. Upload one and select it again.",
            )


@router.get("/site/pages/{slug}")
async def public_site_page(slug: Slug, request: Request, session: PublicSession) -> dict[str, Any]:
    await ratelimit.enforce(f"site-page:{client_ip(request) or 'unknown'}", 120, 60)
    view = await _view(session, slug)
    return {"slug": slug, "content": view["content"]}


@router.get("/admin/site-pages")
async def admin_site_pages(_: StaffDep, session: StaffSession) -> list[dict[str, Any]]:
    return [await _view(session, slug) for slug in site_pages.PAGE_SLUGS]


@router.get("/admin/site-pages/{slug}")
async def admin_site_page(slug: Slug, _: StaffDep, session: StaffSession) -> dict[str, Any]:
    return await _view(session, slug)


@router.put("/admin/site-pages/{slug}")
async def admin_update_site_page(
    slug: Slug,
    body: dict[str, Any],
    request: Request,
    staff: StaffDep,
    session: StaffSession,
) -> dict[str, Any]:
    try:
        content = site_pages.validate_content(slug, body.get("content"))
    except ValidationError as error:
        raise ApiError("invalid_request", _problem(error) + ". Fix the listed fields.") from None
    if slug == "landing_video":
        await _check_media(session, content)
    key = site_pages.setting_key(slug)
    row = await session.get(PlatformSetting, key)
    if row is None:
        session.add(PlatformSetting(key=key, value=site_pages.dump_content(content)))
    else:
        row.value = site_pages.dump_content(content)
        row.updated_at = datetime.now(UTC)
    await session.flush()
    await audit.record(
        session,
        actor_type="staff",
        actor_id=staff.id,
        action="site_page.update",
        payload={"slug": slug},
        ip=client_ip(request),
    )
    return await _view(session, slug)


@router.delete("/admin/site-pages/{slug}", status_code=status.HTTP_200_OK)
async def admin_reset_site_page(
    slug: Slug, request: Request, staff: StaffDep, session: StaffSession
) -> dict[str, Any]:
    row = await session.get(PlatformSetting, site_pages.setting_key(slug))
    if row is not None:
        await session.delete(row)
        await session.flush()
    await audit.record(
        session,
        actor_type="staff",
        actor_id=staff.id,
        action="site_page.reset",
        payload={"slug": slug},
        ip=client_ip(request),
    )
    return await _view(session, slug)
