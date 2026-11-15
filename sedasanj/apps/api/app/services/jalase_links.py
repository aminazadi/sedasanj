"""Link a personal Jalase-Negar account to a SedaSanj organization.

The app keeps two keys: the personal one and an organization device key made from the
organization's normal pairing code.  This module records that link (so it can be listed and
revoked) and never moves data: meetings sent with the organization key are the organization's.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid5

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiError
from app.models import (
    ApiKey,
    JalaseAccountLink,
    Meeting,
    MeetingDocument,
    MeetingDocumentVersion,
    MeetingSegment,
    Tenant,
)
from app.routers.meetings import redeem_pairing_code
from app.schemas import MeetingPairIn
from app.services import audit

PRODUCT = "jalase_negar"
IMPORT_MAX = 50


async def link(
    session: AsyncSession,
    *,
    personal_tenant_id: UUID,
    personal_user_id: UUID,
    payload: MeetingPairIn,
    ip: str | None,
) -> dict[str, Any]:
    """Redeem an organization pairing code for this personal account."""
    personal = await session.get(Tenant, personal_tenant_id)
    if personal is None or personal.product != PRODUCT:
        raise ApiError("forbidden", "این بخش فقط برای حساب شخصی جلسه‌نگار است.")
    try:
        async with session.begin_nested():
            out, key_id, org_tenant_id, org_user_id = await redeem_pairing_code(
                session, payload, ip
            )
            org = await session.get(Tenant, org_tenant_id)
            if org is None or org.product == PRODUCT:
                raise ApiError(
                    "link_invalid_target",
                    "این کد مربوط به یک سازمان صداسنج نیست؛ کد را از پنل سازمان بگیرید.",
                )
            row = JalaseAccountLink(
                personal_tenant_id=personal_tenant_id,
                personal_user_id=personal_user_id,
                org_tenant_id=org_tenant_id,
                org_user_id=org_user_id,
                org_api_key_id=key_id,
            )
            session.add(row)
            await session.flush()
    except IntegrityError as error:
        raise ApiError(
            "link_already_exists",
            "این حساب قبلاً به همین سازمان وصل است؛ اتصال قبلی را قطع کنید و دوباره وصل شوید.",
        ) from error
    await audit.record(
        session,
        actor_type="user",
        actor_id=personal_user_id,
        tenant_id=personal_tenant_id,
        action="jalase.link.created",
        payload={"link_id": str(row.id), "org_tenant_id": str(org_tenant_id)},
        ip=ip,
    )
    return {
        "link_id": str(row.id),
        "token": out.token,
        "token_prefix": out.token_prefix,
        "organization": out.tenant.name,
        "user": out.user.display_name,
    }


async def list_links(session: AsyncSession, personal_tenant_id: UUID) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(JalaseAccountLink, Tenant.name)
            .join(Tenant, Tenant.id == JalaseAccountLink.org_tenant_id)
            .where(
                JalaseAccountLink.personal_tenant_id == personal_tenant_id,
                JalaseAccountLink.status == "active",
            )
            .order_by(JalaseAccountLink.linked_at)
        )
    ).all()
    return [
        {"id": str(row.id), "organization": name, "linked_at": row.linked_at} for row, name in rows
    ]


async def revoke(
    session: AsyncSession, personal_tenant_id: UUID, personal_user_id: UUID, link_id: UUID
) -> None:
    """Revoke the organization key. Data stays where it was made."""
    row = (
        await session.execute(
            select(JalaseAccountLink)
            .where(
                JalaseAccountLink.id == link_id,
                JalaseAccountLink.personal_tenant_id == personal_tenant_id,
                JalaseAccountLink.status == "active",
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        raise ApiError("link_not_found", "این اتصال پیدا نشد یا قبلاً قطع شده است.")
    now = datetime.now(UTC)
    key = await session.get(ApiKey, row.org_api_key_id, with_for_update=True)
    if key is not None and key.revoked_at is None:
        key.revoked_at = now
    row.status = "revoked"
    row.revoked_at = now
    await audit.record(
        session,
        actor_type="user",
        actor_id=personal_user_id,
        tenant_id=personal_tenant_id,
        action="jalase.link.revoked",
        payload={"link_id": str(link_id)},
    )


async def import_meetings(
    session: AsyncSession,
    *,
    personal_tenant_id: UUID,
    personal_user_id: UUID,
    link_id: UUID,
    meeting_ids: list[UUID],
) -> dict[str, Any]:
    """Copy finished personal meetings (text, segments, finished documents) into the organization.

    The originals stay.  Importing a meeting twice is harmless: the copy gets a client id derived
    from the link and the source meeting, so the second attempt is reported as already imported.
    A meeting with no stored text and no finished document (kept off the server) is refused as a
    whole, before anything is written.
    """
    row = (
        await session.execute(
            select(JalaseAccountLink).where(
                JalaseAccountLink.id == link_id,
                JalaseAccountLink.personal_tenant_id == personal_tenant_id,
                JalaseAccountLink.status == "active",
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise ApiError("link_not_found", "این اتصال پیدا نشد یا قبلاً قطع شده است.")
    ids = list(dict.fromkeys(meeting_ids))[:IMPORT_MAX]
    meetings = (
        (
            await session.execute(
                select(Meeting).where(
                    Meeting.tenant_id == personal_tenant_id,
                    Meeting.owner_user_id == personal_user_id,
                    Meeting.id.in_(ids),
                    Meeting.status == "complete",
                )
            )
        )
        .scalars()
        .all()
    )
    if len(meetings) != len(ids):
        raise ApiError("not_found", "یکی از جلسه‌ها پیدا نشد یا هنوز تمام نشده است.")
    plan: list[tuple[Meeting, list[MeetingSegment], list[MeetingDocument]]] = []
    for meeting in meetings:
        segments = list(
            (
                await session.execute(
                    select(MeetingSegment)
                    .where(MeetingSegment.meeting_id == meeting.id)
                    .order_by(MeetingSegment.t_start_ms)
                )
            )
            .scalars()
            .all()
        )
        documents = list(
            (
                await session.execute(
                    select(MeetingDocument).where(
                        MeetingDocument.meeting_id == meeting.id, MeetingDocument.status == "done"
                    )
                )
            )
            .scalars()
            .all()
        )
        if not segments and not documents:
            raise ApiError(
                "import_document_purged",
                "این جلسه روی سرور متنی ندارد (پاک شده است)؛ آن را از انتخاب خارج کنید.",
            )
        plan.append((meeting, segments, documents))
    imported: list[str] = []
    existing: list[str] = []
    for meeting, segments, documents in plan:
        copy_id = uuid5(link_id, str(meeting.id))
        try:
            async with session.begin_nested():
                copy = Meeting(
                    tenant_id=row.org_tenant_id,
                    owner_user_id=row.org_user_id,
                    client_meeting_id=copy_id,
                    title=meeting.title,
                    status="complete",
                    started_at=meeting.started_at,
                    ended_at=meeting.ended_at,
                    duration_ms=meeting.duration_ms,
                    input_kind="text",
                    asr_identity=meeting.asr_identity,
                    progress_pct=100,
                )
                session.add(copy)
                await session.flush()
                for seg in segments:
                    session.add(
                        MeetingSegment(
                            tenant_id=row.org_tenant_id,
                            meeting_id=copy.id,
                            t_start_ms=seg.t_start_ms,
                            t_end_ms=seg.t_end_ms,
                            speaker_idx=seg.speaker_idx,
                            overlap=seg.overlap,
                            speaker_confidence=seg.speaker_confidence,
                            source=seg.source,
                            text=seg.text,
                        )
                    )
                for doc in documents:
                    new_doc = MeetingDocument(
                        tenant_id=row.org_tenant_id,
                        meeting_id=copy.id,
                        output_type_code=doc.output_type_code,
                        output_type_version=doc.output_type_version,
                        input_values=doc.input_values,
                        user_note=doc.user_note,
                        status="done",
                        progress_pct=100,
                    )
                    session.add(new_doc)
                    await session.flush()
                    versions = (
                        (
                            await session.execute(
                                select(MeetingDocumentVersion).where(
                                    MeetingDocumentVersion.document_id == doc.id
                                )
                            )
                        )
                        .scalars()
                        .all()
                    )
                    for ver in versions:
                        session.add(
                            MeetingDocumentVersion(
                                tenant_id=row.org_tenant_id,
                                document_id=new_doc.id,
                                version=ver.version,
                                markdown=ver.markdown,
                                structured=ver.structured,
                                source=ver.source,
                                model=ver.model,
                                provider=ver.provider,
                                prompt_sha256=ver.prompt_sha256,
                                is_selected=ver.is_selected,
                            )
                        )
            imported.append(str(meeting.id))
        except IntegrityError:
            existing.append(str(meeting.id))
    await audit.record(
        session,
        actor_type="user",
        actor_id=personal_user_id,
        tenant_id=personal_tenant_id,
        action="jalase.link.import",
        payload={"link_id": str(link_id), "imported": len(imported), "existing": len(existing)},
    )
    return {"imported": imported, "already_imported": existing}
