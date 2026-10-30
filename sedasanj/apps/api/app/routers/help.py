"""Help center: public reading (articles, search, error-code lookup, media) and staff authoring."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import (
    Principal,
    PublicSession,
    StaffDep,
    StaffSession,
    client_ip,
    require_staff_roles,
)
from app.errors import ApiError
from app.models import HelpArticle, HelpCategory, HelpErrorCode, HelpMedia
from app.schemas import (
    HelpArticleIn,
    HelpArticleList,
    HelpArticleOut,
    HelpArticleSummary,
    HelpArticleUpdate,
    HelpCategoryIn,
    HelpCategoryOut,
    HelpErrorCodeIn,
    HelpErrorCodeOut,
    HelpMediaOut,
)
from app.services import audit, help_content, ratelimit
from app.services.storage import get_storage

router = APIRouter(tags=["help"])

HelpAuthorDep = Annotated[Principal, Depends(require_staff_roles("super_admin"))]
_PUBLIC_RATE = (120, 60)


async def _limit(request: Request) -> None:
    await ratelimit.enforce(f"help:{client_ip(request) or 'unknown'}", *_PUBLIC_RATE)


def _media_url(media_id: UUID) -> str:
    return f"/v1/help/media/{media_id}"


def _like(value: str) -> str:
    return "%" + re.sub(r"([\\%_])", r"\\\1", value) + "%"


async def _codes_of(session: AsyncSession, article_ids: list[UUID]) -> dict[UUID, list[str]]:
    if not article_ids:
        return {}
    rows = await session.execute(
        select(HelpErrorCode.article_id, HelpErrorCode.code)
        .where(HelpErrorCode.article_id.in_(article_ids))
        .order_by(HelpErrorCode.code)
    )
    out: dict[UUID, list[str]] = {}
    for article_id, code in rows.all():
        out.setdefault(article_id, []).append(code)
    return out


def _article_out(article: HelpArticle, codes: list[str]) -> HelpArticleOut:
    data = HelpArticleOut.model_validate(article)
    data.error_codes = codes
    return data


def _check_slug(slug: str) -> str:
    slug = slug.strip().lower()
    if not help_content.SLUG_RE.match(slug):
        raise ApiError("invalid_request", "slug must be lowercase letters, digits and hyphens")
    return slug


def _check_codes(codes: list[str]) -> list[str]:
    cleaned: list[str] = []
    for code in codes:
        code = code.strip()
        if not help_content.ERROR_CODE_RE.match(code):
            raise ApiError("invalid_request", f"invalid error code: {code[:40]}")
        if code not in cleaned:
            cleaned.append(code)
    return cleaned


async def _link_codes(session: AsyncSession, article: HelpArticle, codes: list[str]) -> None:
    """Make exactly `codes` point at this article (other codes keep their own articles)."""
    await session.execute(
        text(
            "UPDATE help_error_codes SET article_id = NULL, updated_at = now() "
            "WHERE article_id = :a AND NOT (code = ANY(:codes))"
        ),
        {"a": article.id, "codes": codes},
    )
    for code in codes:
        stmt = pg_insert(HelpErrorCode).values(code=code, article_id=article.id)
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=[HelpErrorCode.code],
                set_={"article_id": article.id, "updated_at": func.now()},
            )
        )


# --- public -----------------------------------------------------------------


@router.get("/v1/help/categories", response_model=list[HelpCategoryOut])
async def public_categories(request: Request, session: PublicSession) -> list[HelpCategoryOut]:
    await _limit(request)
    counts = dict(
        (
            await session.execute(
                select(HelpArticle.category_id, func.count())
                .where(HelpArticle.status == "published")
                .group_by(HelpArticle.category_id)
            )
        ).all()
    )
    categories = (
        await session.execute(
            select(HelpCategory).order_by(HelpCategory.position, HelpCategory.title)
        )
    ).scalars()
    out = []
    for category in categories:
        item = HelpCategoryOut.model_validate(category)
        item.article_count = int(counts.get(category.id, 0))
        out.append(item)
    return out


@router.get("/v1/help/articles", response_model=HelpArticleList)
async def public_articles(
    request: Request,
    session: PublicSession,
    category: Annotated[str | None, Query(max_length=80)] = None,
    q: Annotated[str | None, Query(max_length=120)] = None,
    kind: Annotated[str | None, Query(pattern="^(article|error|faq)$")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    offset: Annotated[int, Query(ge=0, le=5000)] = 0,
) -> HelpArticleList:
    await _limit(request)
    where = [HelpArticle.status == "published"]
    if kind:
        where.append(HelpArticle.kind == kind)
    if category:
        where.append(
            HelpArticle.category_id
            == select(HelpCategory.id).where(HelpCategory.slug == category).scalar_subquery()
        )
    order = [
        HelpArticle.published_at.desc().nulls_last(),
        HelpArticle.position,
        HelpArticle.title,
    ]
    if q and q.strip():
        term = q.strip()
        tsquery = func.plainto_tsquery("simple", term)
        where.append(
            or_(
                text("search_tsv @@ plainto_tsquery('simple', :term)").bindparams(term=term),
                HelpArticle.title.ilike(_like(term), escape="\\"),
                HelpArticle.slug == term.lower(),
            )
        )
        order = [func.ts_rank(text("search_tsv"), tsquery).desc(), HelpArticle.title]
    total = (
        await session.execute(select(func.count()).select_from(HelpArticle).where(*where))
    ).scalar_one()
    rows = (
        await session.execute(
            select(HelpArticle).where(*where).order_by(*order).limit(limit).offset(offset)
        )
    ).scalars()
    return HelpArticleList(
        items=[HelpArticleSummary.model_validate(r) for r in rows], total=int(total)
    )


@router.get("/v1/help/articles/{slug}", response_model=HelpArticleOut)
async def public_article(slug: str, request: Request, session: PublicSession) -> HelpArticleOut:
    await _limit(request)
    article = (
        await session.execute(
            select(HelpArticle).where(HelpArticle.slug == slug, HelpArticle.status == "published")
        )
    ).scalar_one_or_none()
    if article is None:
        raise ApiError("not_found", "article not found")
    return _article_out(article, (await _codes_of(session, [article.id])).get(article.id, []))


@router.get("/v1/help/errors/{code}", response_model=HelpErrorCodeOut)
async def public_error_code(
    code: str, request: Request, session: PublicSession
) -> HelpErrorCodeOut:
    """Deep link target used by the FreePBX module: /help/errors/SS-UPL-0401."""
    await _limit(request)
    if not help_content.ERROR_CODE_RE.match(code):
        raise ApiError("not_found", "error code not found")
    row = (
        await session.execute(
            select(HelpErrorCode, HelpArticle)
            .join(HelpArticle, HelpArticle.id == HelpErrorCode.article_id, isouter=True)
            .where(func.upper(HelpErrorCode.code) == code.upper())
        )
    ).first()
    if row is None:
        raise ApiError("not_found", "error code not found")
    entry, article = row
    published = article is not None and article.status == "published"
    return HelpErrorCodeOut(
        code=entry.code,
        source=entry.source,  # type: ignore[arg-type]
        severity=entry.severity,  # type: ignore[arg-type]
        title=entry.title,
        quick_action=entry.quick_action,
        article_slug=article.slug if published else None,
        article_title=article.title if published else None,
        article_published=published,
    )


@router.get("/v1/help/media/{media_id}")
async def public_media(
    media_id: UUID, request: Request, session: PublicSession
) -> StreamingResponse:
    await _limit(request)
    media = await session.get(HelpMedia, media_id)
    if media is None:
        raise ApiError("not_found", "media not found")

    async def body() -> AsyncIterator[bytes]:
        async for chunk in get_storage().iter_chunks(media.object_key):
            yield chunk

    return StreamingResponse(
        body(),
        media_type=media.content_type,
        headers={
            "Cache-Control": "public, max-age=86400",
            "X-Content-Type-Options": "nosniff",
            "Content-Length": str(media.size_bytes),
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )


# --- staff ------------------------------------------------------------------


@router.get("/v1/admin/help/categories", response_model=list[HelpCategoryOut])
async def admin_categories(_: StaffDep, session: StaffSession) -> list[HelpCategoryOut]:
    counts = dict(
        (
            await session.execute(
                select(HelpArticle.category_id, func.count()).group_by(HelpArticle.category_id)
            )
        ).all()
    )
    rows = (
        await session.execute(
            select(HelpCategory).order_by(HelpCategory.position, HelpCategory.title)
        )
    ).scalars()
    out = []
    for category in rows:
        item = HelpCategoryOut.model_validate(category)
        item.article_count = int(counts.get(category.id, 0))
        out.append(item)
    return out


@router.post(
    "/v1/admin/help/categories", response_model=HelpCategoryOut, status_code=status.HTTP_201_CREATED
)
async def admin_create_category(
    body: HelpCategoryIn, request: Request, staff: HelpAuthorDep, session: StaffSession
) -> HelpCategoryOut:
    slug = _check_slug(body.slug)
    if (await session.execute(select(HelpCategory.id).where(HelpCategory.slug == slug))).first():
        raise ApiError("conflict_idempotency", "a category with this slug already exists")
    category = HelpCategory(
        slug=slug, title=body.title.strip(), description=body.description, position=body.position
    )
    session.add(category)
    await session.flush()
    await session.refresh(category)
    await audit.record(
        session,
        actor_type="staff",
        actor_id=staff.id,
        action="help_category.create",
        payload={"slug": slug},
        ip=client_ip(request),
    )
    return HelpCategoryOut.model_validate(category)


@router.put("/v1/admin/help/categories/{category_id}", response_model=HelpCategoryOut)
async def admin_update_category(
    category_id: UUID,
    body: HelpCategoryIn,
    request: Request,
    staff: HelpAuthorDep,
    session: StaffSession,
) -> HelpCategoryOut:
    category = await session.get(HelpCategory, category_id)
    if category is None:
        raise ApiError("not_found", "category not found")
    slug = _check_slug(body.slug)
    clash = (
        await session.execute(
            select(HelpCategory.id).where(HelpCategory.slug == slug, HelpCategory.id != category_id)
        )
    ).first()
    if clash:
        raise ApiError("conflict_idempotency", "a category with this slug already exists")
    category.slug, category.title = slug, body.title.strip()
    category.description, category.position = body.description, body.position
    category.updated_at = datetime.now(UTC)
    await audit.record(
        session,
        actor_type="staff",
        actor_id=staff.id,
        action="help_category.update",
        payload={"category_id": str(category_id)},
        ip=client_ip(request),
    )
    return HelpCategoryOut.model_validate(category)


@router.delete("/v1/admin/help/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def admin_delete_category(
    category_id: UUID, request: Request, staff: HelpAuthorDep, session: StaffSession
) -> None:
    category = await session.get(HelpCategory, category_id)
    if category is None:
        raise ApiError("not_found", "category not found")
    await session.delete(category)  # articles keep existing with category_id set to NULL
    await audit.record(
        session,
        actor_type="staff",
        actor_id=staff.id,
        action="help_category.delete",
        payload={"slug": category.slug},
        ip=client_ip(request),
    )


@router.get("/v1/admin/help/articles", response_model=HelpArticleList)
async def admin_articles(
    _: StaffDep,
    session: StaffSession,
    status_filter: Annotated[
        str | None, Query(alias="status", pattern="^(draft|published)$")
    ] = None,
    kind: Annotated[str | None, Query(pattern="^(article|error|faq)$")] = None,
    q: Annotated[str | None, Query(max_length=120)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=10000)] = 0,
) -> HelpArticleList:
    where = []
    if status_filter:
        where.append(HelpArticle.status == status_filter)
    if kind:
        where.append(HelpArticle.kind == kind)
    if q and q.strip():
        where.append(
            or_(
                HelpArticle.title.ilike(_like(q.strip()), escape="\\"),
                HelpArticle.slug.ilike(_like(q.strip()), escape="\\"),
            )
        )
    total = (
        await session.execute(select(func.count()).select_from(HelpArticle).where(*where))
    ).scalar_one()
    rows = (
        await session.execute(
            select(HelpArticle)
            .where(*where)
            .order_by(HelpArticle.updated_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).scalars()
    return HelpArticleList(
        items=[HelpArticleSummary.model_validate(r) for r in rows], total=int(total)
    )


@router.get("/v1/admin/help/articles/{article_id}", response_model=HelpArticleOut)
async def admin_article(article_id: UUID, _: StaffDep, session: StaffSession) -> HelpArticleOut:
    article = await session.get(HelpArticle, article_id)
    if article is None:
        raise ApiError("not_found", "article not found")
    return _article_out(article, (await _codes_of(session, [article.id])).get(article.id, []))


@router.post(
    "/v1/admin/help/articles", response_model=HelpArticleOut, status_code=status.HTTP_201_CREATED
)
async def admin_create_article(
    body: HelpArticleIn, request: Request, staff: HelpAuthorDep, session: StaffSession
) -> HelpArticleOut:
    slug = _check_slug(body.slug)
    if (await session.execute(select(HelpArticle.id).where(HelpArticle.slug == slug))).first():
        raise ApiError("conflict_idempotency", "an article with this slug already exists")
    codes = _check_codes(body.error_codes)
    html, plain = help_content.sanitize_help_html(body.body_html)
    article = HelpArticle(
        slug=slug,
        title=body.title.strip(),
        summary=body.summary.strip(),
        body_html=html,
        body_plain=plain,
        kind=body.kind,
        category_id=body.category_id,
        position=body.position,
        status="draft",
        created_by=staff.id,
    )
    session.add(article)
    await session.flush()
    await _link_codes(session, article, codes)
    await session.refresh(article)
    await audit.record(
        session,
        actor_type="staff",
        actor_id=staff.id,
        action="help_article.create",
        payload={"article_id": str(article.id), "slug": slug},
        ip=client_ip(request),
    )
    return _article_out(article, codes)


@router.patch("/v1/admin/help/articles/{article_id}", response_model=HelpArticleOut)
async def admin_update_article(
    article_id: UUID,
    body: HelpArticleUpdate,
    request: Request,
    staff: HelpAuthorDep,
    session: StaffSession,
) -> HelpArticleOut:
    article = await session.get(HelpArticle, article_id)
    if article is None:
        raise ApiError("not_found", "article not found")
    changed: list[str] = []
    if body.slug is not None:
        slug = _check_slug(body.slug)
        clash = (
            await session.execute(
                select(HelpArticle.id).where(HelpArticle.slug == slug, HelpArticle.id != article_id)
            )
        ).first()
        if clash:
            raise ApiError("conflict_idempotency", "an article with this slug already exists")
        article.slug = slug
        changed.append("slug")
    if body.title is not None:
        article.title = body.title.strip()
        changed.append("title")
    if body.summary is not None:
        article.summary = body.summary.strip()
        changed.append("summary")
    if body.body_html is not None:
        article.body_html, article.body_plain = help_content.sanitize_help_html(body.body_html)
        changed.append("body")
    if body.kind is not None:
        article.kind = body.kind
        changed.append("kind")
    if body.clear_category:
        article.category_id = None
        changed.append("category")
    elif body.category_id is not None:
        article.category_id = body.category_id
        changed.append("category")
    if body.position is not None:
        article.position = body.position
        changed.append("position")
    article.updated_at = datetime.now(UTC)
    if body.error_codes is not None:
        codes = _check_codes(body.error_codes)
        await _link_codes(session, article, codes)
        changed.append("error_codes")
    await session.flush()
    await audit.record(
        session,
        actor_type="staff",
        actor_id=staff.id,
        action="help_article.update",
        payload={"article_id": str(article_id), "fields": changed},
        ip=client_ip(request),
    )
    return _article_out(article, (await _codes_of(session, [article.id])).get(article.id, []))


@router.post("/v1/admin/help/articles/{article_id}/publish", response_model=HelpArticleOut)
async def admin_publish_article(
    article_id: UUID, request: Request, staff: HelpAuthorDep, session: StaffSession
) -> HelpArticleOut:
    article = await session.get(HelpArticle, article_id)
    if article is None:
        raise ApiError("not_found", "article not found")
    if not article.body_plain.strip() or not article.title.strip():
        raise ApiError(
            "invalid_request", "an article needs a title and content before it is published"
        )
    article.status = "published"
    article.published_at = article.published_at or datetime.now(UTC)
    article.updated_at = datetime.now(UTC)
    await audit.record(
        session,
        actor_type="staff",
        actor_id=staff.id,
        action="help_article.publish",
        payload={"article_id": str(article_id), "slug": article.slug},
        ip=client_ip(request),
    )
    return _article_out(article, (await _codes_of(session, [article.id])).get(article.id, []))


@router.post("/v1/admin/help/articles/{article_id}/unpublish", response_model=HelpArticleOut)
async def admin_unpublish_article(
    article_id: UUID, request: Request, staff: HelpAuthorDep, session: StaffSession
) -> HelpArticleOut:
    article = await session.get(HelpArticle, article_id)
    if article is None:
        raise ApiError("not_found", "article not found")
    article.status = "draft"
    article.updated_at = datetime.now(UTC)
    await audit.record(
        session,
        actor_type="staff",
        actor_id=staff.id,
        action="help_article.unpublish",
        payload={"article_id": str(article_id)},
        ip=client_ip(request),
    )
    return _article_out(article, (await _codes_of(session, [article.id])).get(article.id, []))


@router.delete("/v1/admin/help/articles/{article_id}", status_code=status.HTTP_204_NO_CONTENT)
async def admin_delete_article(
    article_id: UUID, request: Request, staff: HelpAuthorDep, session: StaffSession
) -> None:
    article = await session.get(HelpArticle, article_id)
    if article is None:
        raise ApiError("not_found", "article not found")
    await session.delete(article)  # error codes keep existing with article_id set to NULL
    await audit.record(
        session,
        actor_type="staff",
        actor_id=staff.id,
        action="help_article.delete",
        payload={"slug": article.slug},
        ip=client_ip(request),
    )


@router.get("/v1/admin/help/error-codes", response_model=list[HelpErrorCodeOut])
async def admin_error_codes(
    _: StaffDep, session: StaffSession, only_missing: Annotated[bool, Query()] = False
) -> list[HelpErrorCodeOut]:
    rows = (
        await session.execute(
            select(HelpErrorCode, HelpArticle)
            .join(HelpArticle, HelpArticle.id == HelpErrorCode.article_id, isouter=True)
            .order_by(HelpErrorCode.code)
        )
    ).all()
    out = []
    for entry, article in rows:
        published = article is not None and article.status == "published"
        if only_missing and published:
            continue
        out.append(
            HelpErrorCodeOut(
                code=entry.code,
                source=entry.source,
                severity=entry.severity,  # type: ignore[arg-type]
                title=entry.title,
                quick_action=entry.quick_action,
                article_slug=article.slug if article else None,
                article_title=article.title if article else None,
                article_published=published,
            )
        )
    return out


@router.put("/v1/admin/help/error-codes/{code}", response_model=HelpErrorCodeOut)
async def admin_put_error_code(
    code: str, body: HelpErrorCodeIn, request: Request, staff: HelpAuthorDep, session: StaffSession
) -> HelpErrorCodeOut:
    code = _check_codes([code])[0]
    if body.article_id is not None and await session.get(HelpArticle, body.article_id) is None:
        raise ApiError("not_found", "article not found")
    stmt = pg_insert(HelpErrorCode).values(
        code=code,
        source=body.source,
        severity=body.severity,
        title=body.title,
        quick_action=body.quick_action,
        article_id=body.article_id,
    )
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=[HelpErrorCode.code],
            set_={
                "source": body.source,
                "severity": body.severity,
                "title": body.title,
                "quick_action": body.quick_action,
                "article_id": body.article_id,
                "updated_at": func.now(),
            },
        )
    )
    await audit.record(
        session,
        actor_type="staff",
        actor_id=staff.id,
        action="help_error_code.put",
        payload={"code": code},
        ip=client_ip(request),
    )
    rows = await admin_error_codes(staff, session)
    return next(r for r in rows if r.code == code)


@router.post("/v1/admin/help/error-codes/seed-module", response_model=dict[str, int])
async def admin_seed_module_codes(
    request: Request, staff: HelpAuthorDep, session: StaffSession
) -> dict[str, int]:
    """Create/refresh the module's catalog entries; article links already set are kept."""
    created = updated = 0
    for entry in help_content.module_error_catalog():
        existing = await session.get(HelpErrorCode, entry["code"])
        if existing is None:
            session.add(
                HelpErrorCode(
                    code=entry["code"],
                    source="module",
                    severity=entry["severity"],
                    title=entry["title"],
                    quick_action=entry["action"],
                )
            )
            created += 1
        else:
            existing.severity, existing.title, existing.quick_action = (
                entry["severity"],
                entry["title"],
                entry["action"],
            )
            existing.updated_at = datetime.now(UTC)
            updated += 1
    await audit.record(
        session,
        actor_type="staff",
        actor_id=staff.id,
        action="help_error_code.seed_module",
        payload={"created": created, "updated": updated},
        ip=client_ip(request),
    )
    return {"created": created, "updated": updated}


@router.delete("/v1/admin/help/error-codes/{code}", status_code=status.HTTP_204_NO_CONTENT)
async def admin_delete_error_code(
    code: str, request: Request, staff: HelpAuthorDep, session: StaffSession
) -> None:
    code = _check_codes([code])[0]
    await session.execute(delete(HelpErrorCode).where(HelpErrorCode.code == code))
    await audit.record(
        session,
        actor_type="staff",
        actor_id=staff.id,
        action="help_error_code.delete",
        payload={"code": code},
        ip=client_ip(request),
    )


@router.get("/v1/admin/help/media", response_model=list[HelpMediaOut])
async def admin_media(_: StaffDep, session: StaffSession) -> list[HelpMediaOut]:
    rows = (
        await session.execute(select(HelpMedia).order_by(HelpMedia.created_at.desc()).limit(500))
    ).scalars()
    out = []
    for media in rows:
        item = HelpMediaOut.model_validate(media)
        item.url = _media_url(media.id)
        out.append(item)
    return out


@router.post(
    "/v1/admin/help/media", response_model=HelpMediaOut, status_code=status.HTTP_201_CREATED
)
async def admin_upload_media(
    request: Request,
    staff: HelpAuthorDep,
    session: StaffSession,
    file: Annotated[UploadFile, File()],
    alt: Annotated[str, Form(max_length=300)] = "",
) -> HelpMediaOut:
    head = await file.read(64)
    sniffed = help_content.sniff_media(head)
    if sniffed is None:
        raise ApiError(
            "invalid_request", "only PNG, JPEG, WebP, GIF, MP4 and WebM files are allowed"
        )
    kind, content_type = sniffed
    limit = help_content.media_limit(kind)
    chunks = [head]
    size = len(head)
    while chunk := await file.read(1024 * 1024):
        size += len(chunk)
        if size > limit:
            raise ApiError(
                "archive_too_large", f"the file is larger than {limit // (1024 * 1024)} MB"
            )
        chunks.append(chunk)
    media_id = uuid4()
    key = f"help-media/{media_id}{help_content.media_extension(content_type)}"
    await get_storage().put(key, b"".join(chunks), content_type)
    name = re.sub(r"[^A-Za-z0-9._-]", "_", (file.filename or "upload"))[:200] or "upload"
    media = HelpMedia(
        id=media_id,
        kind=kind,
        object_key=key,
        filename=name,
        content_type=content_type,
        size_bytes=size,
        alt=alt.strip(),
        created_by=staff.id,
    )
    session.add(media)
    await session.flush()
    await audit.record(
        session,
        actor_type="staff",
        actor_id=staff.id,
        action="help_media.upload",
        payload={"media_id": str(media_id), "kind": kind, "bytes": size},
        ip=client_ip(request),
    )
    await session.refresh(media)
    item = HelpMediaOut.model_validate(media)
    item.url = _media_url(media.id)
    return item


@router.delete("/v1/admin/help/media/{media_id}", status_code=status.HTTP_204_NO_CONTENT)
async def admin_delete_media(
    media_id: UUID, request: Request, staff: HelpAuthorDep, session: StaffSession
) -> None:
    media = await session.get(HelpMedia, media_id)
    if media is None:
        raise ApiError("not_found", "media not found")
    in_use = (
        await session.execute(
            select(func.count())
            .select_from(HelpArticle)
            .where(HelpArticle.body_html.contains(str(media_id)))
        )
    ).scalar_one()
    if in_use:
        raise ApiError(
            "conflict_idempotency",
            f"this file is used by {in_use} article(s); remove it from them first",
        )
    await get_storage().delete(media.object_key)
    await session.delete(media)
    await audit.record(
        session,
        actor_type="staff",
        actor_id=staff.id,
        action="help_media.delete",
        payload={"media_id": str(media_id)},
        ip=client_ip(request),
    )
