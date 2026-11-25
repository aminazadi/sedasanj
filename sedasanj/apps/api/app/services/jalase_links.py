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

from app.db import control_session_scope, session_scope
from app.errors import ApiError
from app.models import (
    ApiKey,
    JalaseAccountLink,
    Meeting,
    MeetingAttendee,
    MeetingDocument,
    MeetingDocumentVersion,
    MeetingMinutes,
    MeetingSegment,
    MeetingSpeaker,
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
    *,
    personal_tenant_id: UUID,
    personal_user_id: UUID,
    link_id: UUID,
    meeting_ids: list[UUID],
) -> dict[str, Any]:
    """Copy finished personal meetings (text, segments, documents, minutes) into the organization.

    The originals stay.  Importing a meeting twice is harmless: the copy gets a client id derived
    from the link and the source meeting, so the second attempt is reported as already imported.
    A meeting with no stored text and no finished document (kept off the server) is refused as a
    whole, before anything is written.

    The personal and organization tenants may live in different databases, so the source is read
    in the personal tenant's session and the copy is written in the organization's session.
    Minutes, speakers and attendees are copied too; without them the organization's copy had a
    transcript but no minutes and `speaker_idx` pointed at nobody.
    """
    async with control_session_scope() as control:
        row = (
            await control.execute(
                select(JalaseAccountLink).where(
                    JalaseAccountLink.id == link_id,
                    JalaseAccountLink.personal_tenant_id == personal_tenant_id,
                    JalaseAccountLink.status == "active",
                )
            )
        ).scalar_one_or_none()
    if row is None:
        raise ApiError("link_not_found", "این اتصال پیدا نشد یا قبلاً قطع شده است.")
    org_tenant_id, org_user_id = row.org_tenant_id, row.org_user_id
    ids = list(dict.fromkeys(meeting_ids))[:IMPORT_MAX]
    plan: list[dict[str, Any]] = []
    async with session_scope(personal_tenant_id) as source:
        meetings = (
            (
                await source.execute(
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
        for meeting in meetings:
            segments = list(
                (
                    await source.execute(
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
                    await source.execute(
                        select(MeetingDocument).where(
                            MeetingDocument.meeting_id == meeting.id,
                            MeetingDocument.status == "done",
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
            versions: dict[UUID, list[MeetingDocumentVersion]] = {}
            for document in documents:
                versions[document.id] = list(
                    (
                        await source.execute(
                            select(MeetingDocumentVersion).where(
                                MeetingDocumentVersion.document_id == document.id
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
            minutes = list(
                (
                    await source.execute(
                        select(MeetingMinutes).where(MeetingMinutes.meeting_id == meeting.id)
                    )
                )
                .scalars()
                .all()
            )
            speakers = list(
                (
                    await source.execute(
                        select(MeetingSpeaker).where(MeetingSpeaker.meeting_id == meeting.id)
                    )
                )
                .scalars()
                .all()
            )
            attendees = list(
                (
                    await source.execute(
                        select(MeetingAttendee).where(MeetingAttendee.meeting_id == meeting.id)
                    )
                )
                .scalars()
                .all()
            )
            plan.append(
                {
                    "meeting": meeting,
                    "segments": segments,
                    "documents": documents,
                    "versions": versions,
                    "minutes": minutes,
                    "speakers": speakers,
                    "attendees": attendees,
                }
            )
    imported: list[str] = []
    existing: list[str] = []
    async with session_scope(org_tenant_id) as target:
        for item in plan:
            meeting = item["meeting"]
            copy_id = uuid5(link_id, str(meeting.id))
            already = (
                await target.execute(
                    select(Meeting.id).where(
                        Meeting.tenant_id == org_tenant_id,
                        Meeting.client_meeting_id == copy_id,
                    )
                )
            ).scalar_one_or_none()
            if already is not None:
                existing.append(str(meeting.id))
                continue
            try:
                async with target.begin_nested():
                    copy = Meeting(
                        tenant_id=org_tenant_id,
                        owner_user_id=org_user_id,
                        client_meeting_id=copy_id,
                        title=meeting.title,
                        status="complete",
                        started_at=meeting.started_at,
                        ended_at=meeting.ended_at,
                        duration_ms=meeting.duration_ms,
                        input_kind="text",
                        asr_identity=meeting.asr_identity,
                        output_type_code=meeting.output_type_code,
                        output_type_input_values=meeting.output_type_input_values,
                        progress_pct=100,
                    )
                    target.add(copy)
                    await target.flush()
                    for seg in item["segments"]:
                        target.add(
                            MeetingSegment(
                                tenant_id=org_tenant_id,
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
                    for speaker in item["speakers"]:
                        # The organization has its own users and profiles; the label is what the
                        # transcript needs, so the personal ids are not carried across.
                        target.add(
                            MeetingSpeaker(
                                tenant_id=org_tenant_id,
                                meeting_id=copy.id,
                                speaker_idx=speaker.speaker_idx,
                                label=speaker.label,
                                user_id=None,
                                profile_id=None,
                                total_ms=speaker.total_ms,
                            )
                        )
                    for attendee in item["attendees"]:
                        target.add(
                            MeetingAttendee(
                                tenant_id=org_tenant_id,
                                meeting_id=copy.id,
                                profile_client_id=attendee.profile_client_id,
                                profile_id=None,
                                name=attendee.name,
                            )
                        )
                    for minutes in item["minutes"]:
                        target.add(
                            MeetingMinutes(
                                tenant_id=org_tenant_id,
                                meeting_id=copy.id,
                                version=minutes.version,
                                content_md=minutes.content_md,
                                structured=minutes.structured,
                                model=minutes.model,
                                provider=minutes.provider,
                                prompt_sha256=minutes.prompt_sha256,
                                is_selected=minutes.is_selected,
                            )
                        )
                    for doc in item["documents"]:
                        new_doc = MeetingDocument(
                            tenant_id=org_tenant_id,
                            meeting_id=copy.id,
                            output_type_code=doc.output_type_code,
                            output_type_version=doc.output_type_version,
                            input_values=doc.input_values,
                            user_note=doc.user_note,
                            status="done",
                            progress_pct=100,
                        )
                        target.add(new_doc)
                        await target.flush()
                        for ver in item["versions"].get(doc.id, []):
                            target.add(
                                MeetingDocumentVersion(
                                    tenant_id=org_tenant_id,
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
    async with session_scope(personal_tenant_id) as source:
        await audit.record(
            source,
            actor_type="user",
            actor_id=personal_user_id,
            tenant_id=personal_tenant_id,
            action="jalase.link.import",
            payload={"link_id": str(link_id), "imported": len(imported), "existing": len(existing)},
        )
    return {"imported": imported, "already_imported": existing}
