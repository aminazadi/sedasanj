from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import session_scope
from app.errors import ApiError
from app.logging import log_context
from app.metrics import credit_rejects_total, ingest_total
from app.models import AudioObject, Call, CreditReservation, Job, Tenant
from app.schemas import IngestAccepted
from app.services import billing, entitlements, outbox, processing_events, progress
from app.services.audio import probe_wav_bytes, probe_wav_file
from app.services.phone_numbers import normalize_call_number
from app.services.storage import get_storage

logger = logging.getLogger(__name__)

DIRECTIONS = ("inbound", "outbound", "internal")


@dataclass(frozen=True)
class IngestResult:
    accepted: IngestAccepted
    replayed: bool


def resolve_uniqueid(raw: str | None) -> str:
    value = (raw or "").strip()
    return value or f"manual-{uuid4()}"


def resolve_window(
    started_at: datetime | None, ended_at: datetime | None, duration_ms: int
) -> tuple[datetime, datetime]:
    span = timedelta(milliseconds=max(duration_ms, 0))
    if started_at is None and ended_at is None:
        ended = datetime.now(UTC)
        return ended - span, ended
    if started_at is None:
        assert ended_at is not None
        return ended_at - span, ended_at
    if ended_at is None:
        return started_at, started_at + span
    if ended_at < started_at:
        raise ApiError("invalid_request", "ended_at must be after started_at")
    return started_at, ended_at


async def accept_upload(
    *,
    tenant_id: UUID,
    payload: bytes | Path,
    asterisk_uniqueid: str,
    caller_number: str,
    dialed_number: str,
    started_at: datetime | None,
    ended_at: datetime | None,
    direction: str | None = None,
    agent_extension: str | None = None,
    campaign_id: str | None = None,
    source: str | None = None,
    external_reference: str | None = None,
    idempotency_key: str | None = None,
) -> IngestResult:
    """§4.3 upload contract: validate, reserve credit, store, queue ASR."""
    settings = get_settings()
    unique_id = resolve_uniqueid(asterisk_uniqueid)
    caller_number = normalize_call_number(caller_number)
    dialed_number = normalize_call_number(dialed_number)
    if not caller_number or not dialed_number:
        raise ApiError("invalid_request", "caller_number and dialed_number are required")
    if direction is not None and direction not in DIRECTIONS:
        raise ApiError("invalid_request", f"direction must be one of {', '.join(DIRECTIONS)}")
    if idempotency_key is not None and idempotency_key.strip() not in ("", unique_id):
        logger.info(
            "idempotency key differs from the asterisk uniqueid; deduplicating on the uniqueid",
            extra={"extra_fields": {"asterisk_uniqueid": unique_id}},
        )

    replay = await _replay(tenant_id, unique_id)
    if replay is not None:
        ingest_total.labels(tenant=str(tenant_id), result="replay").inc()
        return IngestResult(accepted=replay, replayed=True)

    payload_size = payload.stat().st_size if isinstance(payload, Path) else len(payload)
    if payload_size == 0:
        raise ApiError("unsupported_audio", "empty upload")
    if payload_size > settings.max_extracted_audio_bytes:
        raise ApiError(
            "unsupported_audio",
            f"audio exceeds {settings.max_extracted_audio_bytes // (1024 * 1024)} MB",
        )

    probe = (
        await probe_wav_file(payload)
        if isinstance(payload, Path)
        else await probe_wav_bytes(payload)
    )
    started_at, ended_at = resolve_window(started_at, ended_at, probe.duration_ms)

    client_ms = max(int((ended_at - started_at).total_seconds() * 1000), 0)
    if client_ms and abs(client_ms - probe.duration_ms) / max(client_ms, 1) > (
        settings.duration_mismatch_tolerance
    ):
        logger.warning(
            "client timestamps disagree with probed duration; trusting the file",
            extra={
                "extra_fields": {
                    "client_ms": client_ms,
                    "probed_ms": probe.duration_ms,
                    "asterisk_uniqueid": unique_id,
                }
            },
        )

    try:
        async with session_scope(tenant_id) as session:
            tenant = await session.get(Tenant, tenant_id)
            if tenant is None:
                raise ApiError("unauthorized", "tenant not found")
            entitlement = await entitlements.require_upload_consumption(
                session,
                tenant_id,
                price_per_minute_toman=tenant.price_per_minute_toman,
            )
            tenant.price_per_minute_toman = entitlement.price_per_minute_toman
            await _assert_quota(session, tenant, probe.duration_ms)

            call = Call(
                tenant_id=tenant_id,
                asterisk_uniqueid=unique_id,
                caller_number=caller_number,
                dialed_number=dialed_number,
                direction=direction,
                agent_extension=agent_extension,
                campaign_id=(campaign_id or "").strip() or None,
                source=(source or "").strip() or None,
                external_reference=(external_reference or "").strip() or None,
                started_at=started_at,
                ended_at=ended_at,
                duration_ms=probe.duration_ms,
                status="received",
                **progress.values_for_status("received"),
            )
            session.add(call)
            await session.flush()
            if agent_extension:
                from app.models import CallOperatorAssignment, User

                operator = (
                    await session.execute(
                        select(User).where(
                            User.tenant_id == tenant_id,
                            User.role == "operator",
                            User.extension == agent_extension,
                        )
                    )
                ).scalar_one_or_none()
                if operator is not None:
                    session.add(
                        CallOperatorAssignment(
                            tenant_id=tenant_id,
                            call_id=call.id,
                            operator_id=operator.id,
                            agent_extension=agent_extension,
                            assignment_source="ingest_exact_extension",
                            confidence=1.0,
                        )
                    )
            log_context(call_id=str(call.id))
            received = progress.values_for_status("received")
            await processing_events.record(
                session,
                tenant_id=tenant_id,
                call_id=call.id,
                kind="pipeline",
                status="received",
                progress_pct=int(received["progress_pct"]),
                message=str(received["progress_detail"]),
            )

            try:
                reservation = await billing.reserve(
                    session, tenant=tenant, call_id=call.id, duration_ms=probe.duration_ms
                )
            except ApiError as exc:
                if exc.code == "insufficient_credit":
                    credit_rejects_total.labels(tenant=str(tenant_id)).inc()
                    ingest_total.labels(tenant=str(tenant_id), result="insufficient_credit").inc()
                raise

            call.status = "reserved"
            reserved = progress.values_for_status("reserved")
            call.progress_pct = int(reserved["progress_pct"])
            call.progress_detail = str(reserved["progress_detail"])
            await processing_events.record(
                session,
                tenant_id=tenant_id,
                call_id=call.id,
                kind="pipeline",
                status="reserved",
                progress_pct=int(reserved["progress_pct"]),
                message=str(reserved["progress_detail"]),
            )
            call_id = call.id
            reservation_id = reservation.id
            retention_days = tenant.audio_retention_days
    except IntegrityError:
        replay = await _replay(tenant_id, unique_id)
        if replay is None:
            raise
        ingest_total.labels(tenant=str(tenant_id), result="replay").inc()
        return IngestResult(accepted=replay, replayed=True)

    object_key = f"{tenant_id}/{call_id}.wav"
    storage = get_storage()
    try:
        if isinstance(payload, Path):
            await storage.put_path(object_key, payload)
        else:
            await storage.put(object_key, payload)
    except Exception as exc:
        async with session_scope(tenant_id) as session:
            await billing.release(session, tenant_id=tenant_id, call_id=call_id)
            await session.execute(
                update(Call)
                .where(Call.id == call_id)
                .values(
                    status="failed_terminal",
                    error_code="storage_unavailable",
                    **progress.values_for_status("failed_terminal"),
                )
            )
            await processing_events.record(
                session,
                tenant_id=tenant_id,
                call_id=call_id,
                kind="pipeline",
                level="error",
                status="failed_terminal",
                message="ذخیره فایل صوتی ناموفق بود",
                error_code="storage_unavailable",
                error_detail=repr(exc),
            )
        ingest_total.labels(tenant=str(tenant_id), result="storage_error").inc()
        logger.exception(
            "audio storage failed",
            extra={"extra_fields": {"tenant_id": str(tenant_id), "call_id": str(call_id)}},
        )
        raise ApiError("internal", "could not store audio") from exc

    try:
        async with session_scope(tenant_id) as session:
            audio = AudioObject(
                tenant_id=tenant_id,
                bucket=storage.bucket,
                object_key=object_key,
                sha256=probe.sha256,
                bytes=probe.bytes,
                sample_rate=probe.sample_rate,
                channels=probe.channels,
                duration_ms=probe.duration_ms,
                expires_at=datetime.now(UTC) + timedelta(days=retention_days),
            )
            session.add(audio)
            await session.flush()
            await session.execute(
                update(Call)
                .where(Call.id == call_id, Call.status == "reserved")
                .values(
                    audio_id=audio.id,
                    status="stored",
                    updated_at=datetime.now(UTC),
                    **progress.values_for_status("stored"),
                )
            )
            stored = progress.values_for_status("stored")
            await processing_events.record(
                session,
                tenant_id=tenant_id,
                call_id=call_id,
                kind="pipeline",
                status="stored",
                progress_pct=int(stored["progress_pct"]),
                message=str(stored["progress_detail"]),
            )
            job = Job(tenant_id=tenant_id, call_id=call_id, kind="asr", status="queued", attempt=0)
            session.add(job)
            await session.flush()
            await processing_events.record(
                session,
                tenant_id=tenant_id,
                call_id=call_id,
                kind="asr",
                status="queued",
                progress_pct=int(stored["progress_pct"]),
                message="تبدیل گفتار در صف پردازش قرار گرفت",
                step_key=f"{job.id}:queued:0",
            )
            outbox_id = await outbox.stage_job(
                session,
                job_id=job.id,
                tenant_id=tenant_id,
                call_id=call_id,
                kind="asr",
            )
    except Exception as exc:
        await storage.delete(object_key)
        async with session_scope(tenant_id) as session:
            await billing.release(session, tenant_id=tenant_id, call_id=call_id)
            await session.execute(
                update(Call)
                .where(Call.id == call_id)
                .values(
                    status="failed_terminal",
                    error_code="internal",
                    **progress.values_for_status("failed_terminal"),
                )
            )
            await processing_events.record(
                session,
                tenant_id=tenant_id,
                call_id=call_id,
                kind="pipeline",
                level="error",
                status="failed_terminal",
                message="ثبت اطلاعات فایل صوتی ناموفق بود",
                error_code="internal",
                error_detail=repr(exc),
            )
        ingest_total.labels(tenant=str(tenant_id), result="metadata_error").inc()
        raise ApiError("internal", "could not record the upload") from exc

    try:
        await outbox.dispatch_one(outbox_id)
    except Exception:
        logger.exception(
            "immediate ASR dispatch failed; durable dispatcher will retry",
            extra={"extra_fields": {"call_id": str(call_id)}},
        )
    ingest_total.labels(tenant=str(tenant_id), result="accepted").inc()
    return IngestResult(
        accepted=IngestAccepted(call_id=call_id, status="queued", reservation_id=reservation_id),
        replayed=False,
    )


async def _reservation_id(session: AsyncSession, call_id: UUID) -> UUID | None:
    result = await session.execute(
        select(CreditReservation.id).where(CreditReservation.call_id == call_id)
    )
    return result.scalar_one_or_none()


async def _replay(tenant_id: UUID, unique_id: str) -> IngestAccepted | None:
    """§4.4: the same `asterisk_uniqueid` always resolves to the original call."""
    async with session_scope(tenant_id) as session:
        existing = (
            await session.execute(
                select(Call).where(Call.tenant_id == tenant_id, Call.asterisk_uniqueid == unique_id)
            )
        ).scalar_one_or_none()
        if existing is None:
            return None
        return IngestAccepted(
            call_id=existing.id,
            status=existing.status,
            reservation_id=await _reservation_id(session, existing.id),
        )


async def _assert_quota(session: AsyncSession, tenant: Tenant, duration_ms: int) -> None:
    """§7.1 `monthly_minute_quota`: refuse once this calendar month is exhausted."""
    if tenant.monthly_minute_quota is None:
        return
    month_start = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    used_ms = int(
        (
            await session.execute(
                select(func.coalesce(func.sum(Call.duration_ms), 0)).where(
                    Call.tenant_id == tenant.id,
                    Call.created_at >= month_start,
                    Call.status != "failed_terminal",
                )
            )
        ).scalar_one()
    )
    if (used_ms + duration_ms) / 60000 > tenant.monthly_minute_quota:
        ingest_total.labels(tenant=str(tenant.id), result="quota_exceeded").inc()
        raise ApiError(
            "quota_exceeded",
            f"monthly quota of {tenant.monthly_minute_quota} minutes is exhausted",
        )
