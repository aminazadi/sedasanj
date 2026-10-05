from __future__ import annotations

import base64
import binascii
import logging
from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated, Any
from typing import cast as type_cast
from uuid import UUID
from zoneinfo import ZoneInfo

from botocore.exceptions import ClientError
from fastapi import APIRouter, File, Form, Query, Request, Response, UploadFile, status
from fastapi.responses import RedirectResponse
from sqlalchemy import Select, and_, cast, delete, func, literal, or_, select, text, update
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import session_scope
from app.deps import OperatorDep, OrgAdminDep, Principal, TenantSession, UserDep, client_ip
from app.errors import ApiError
from app.models import (
    AnalysisRun,
    AsrTranscriptRevision,
    AsrTranscriptRevisionSegment,
    AudioObject,
    Call,
    CallInsight,
    CreditReservation,
    Job,
    LedgerEntry,
    ProcessingEvent,
    SalesInsight,
    Tenant,
    Transcript,
    TranscriptRevision,
    TranscriptRevisionSegment,
    Utterance,
    WebhookDelivery,
)
from app.schemas import (
    AnalyticsBucket,
    AnalyticsSummary,
    AnalyticsTrendPoint,
    AsrTranscriptRevisionOut,
    CallDetail,
    CallPage,
    CallSummary,
    CorrectionStatusOut,
    IngestAccepted,
    InsightsOut,
    ProcessingEventOut,
    SalesBlock,
    Sentiment,
    SentimentTrajectory,
    UtteranceOut,
)
from app.sentiment import SENTIMENT_SET, caller_trajectory, normalize_sentiment
from app.services import (
    audit,
    billing,
    follow_up_tasks,
    operator_scope,
    outbox,
    processing_events,
    progress,
    ratelimit,
)
from app.services.asr_revisions import activate_existing
from app.services.ingest import accept_upload
from app.services.platform import (
    capability_model,
    effective_extract_prompt,
    effective_models,
    resolve_provider_settings,
)
from app.services.progress import resolve as resolve_progress
from app.services.storage import get_storage
from app.services.transcript_corrections import create_revision

router = APIRouter(prefix="/v1", tags=["calls"])
logger = logging.getLogger(__name__)
TEHRAN = ZoneInfo("Asia/Tehran")


def _encode_cursor(started_at: datetime, call_id: UUID) -> str:
    raw = f"{started_at.isoformat()}|{call_id}".encode()
    return base64.urlsafe_b64encode(raw).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    try:
        started_raw, call_raw = base64.urlsafe_b64decode(cursor.encode()).decode().split("|", 1)
        return datetime.fromisoformat(started_raw), UUID(call_raw)
    except (ValueError, binascii.Error) as exc:
        raise ApiError("invalid_request", "malformed cursor") from exc


def _parse_date_boundary(value: str | None, *, end: bool) -> datetime | None:
    if not value:
        return None
    try:
        if len(value) == 10:
            selected = date.fromisoformat(value)
            local = datetime.combine(selected, time.max if end else time.min, tzinfo=TEHRAN)
            return local.astimezone(UTC)
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=TEHRAN)
        return parsed.astimezone(UTC)
    except ValueError as exc:
        raise ApiError("invalid_request", "invalid date filter") from exc


def _apply_filters(
    stmt: Select[Any],
    *,
    from_date: datetime | None,
    to_date: datetime | None,
    q: str | None,
    intent: str | None,
    sentiment: str | None,
    number: str | None,
) -> Select[Any]:
    if from_date is not None:
        stmt = stmt.where(Call.started_at >= from_date)
    if to_date is not None:
        stmt = stmt.where(Call.started_at <= to_date)
    if intent:
        stmt = stmt.where(CallInsight.intent == intent)
    if sentiment:
        try:
            mapped = str(normalize_sentiment(sentiment))
        except ValueError:
            mapped = sentiment
        stmt = stmt.where(CallInsight.sentiment == mapped)
    if number:
        pattern = f"%{number}%"
        stmt = stmt.where(or_(Call.caller_number.ilike(pattern), Call.dialed_number.ilike(pattern)))
    if q:
        tsquery = func.websearch_to_tsquery("simple", q)
        pattern = f"%{q}%"
        stmt = stmt.where(
            or_(
                cast(Transcript.search, TSVECTOR).op("@@")(tsquery),
                Call.caller_number.ilike(pattern),
                Call.dialed_number.ilike(pattern),
                CallInsight.summary.ilike(pattern),
            )
        )
    return stmt


@router.get("/calls", response_model=CallPage)
async def list_calls(
    principal: UserDep,
    session: TenantSession,
    cursor: Annotated[str | None, Query()] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    from_: Annotated[str | None, Query(alias="from")] = None,
    to: Annotated[str | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    intent: Annotated[str | None, Query()] = None,
    sentiment: Annotated[str | None, Query()] = None,
    number: Annotated[str | None, Query()] = None,
    direction: Annotated[str | None, Query()] = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
) -> CallPage:
    stmt = (
        select(Call, CallInsight)
        .outerjoin(
            CallInsight,
            (CallInsight.call_id == Call.id) & (CallInsight.tenant_id == principal.tenant_id),
        )
        .outerjoin(
            Transcript,
            (Transcript.call_id == Call.id) & (Transcript.tenant_id == principal.tenant_id),
        )
        .where(Call.tenant_id == principal.tenant_id)
        .order_by(Call.started_at.desc(), Call.id.desc())
        .limit(limit + 1)
    )
    stmt = operator_scope.apply_operator_scope(stmt, principal)
    stmt = _apply_filters(
        stmt,
        from_date=_parse_date_boundary(from_, end=False),
        to_date=_parse_date_boundary(to, end=True),
        q=q,
        intent=intent,
        sentiment=sentiment,
        number=number,
    )
    if status_filter:
        stmt = stmt.where(Call.status == status_filter)
    if direction:
        stmt = stmt.where(Call.direction == direction)
    total = int(
        (
            await session.execute(
                select(func.count()).select_from(stmt.order_by(None).limit(None).subquery())
            )
        ).scalar_one()
    )
    if cursor:
        started_at, call_id = _decode_cursor(cursor)
        stmt = stmt.where(
            or_(
                Call.started_at < started_at,
                and_(Call.started_at == started_at, Call.id < call_id),
            )
        )
    elif offset:
        stmt = stmt.offset(offset)

    rows = (await session.execute(stmt)).all()
    has_more = len(rows) > limit
    rows = rows[:limit]

    items = [
        _summary(call, insight, hide_billing=operator_scope.is_operator(principal))
        for call, insight in rows
    ]
    next_cursor = (
        _encode_cursor(rows[-1][0].started_at, rows[-1][0].id) if has_more and rows else None
    )
    page = (offset // limit) + 1 if cursor is None else 1
    pages = max(1, (total + limit - 1) // limit)
    return CallPage(
        items=items,
        next_cursor=next_cursor,
        total=total,
        page=page,
        page_size=limit,
        pages=pages,
    )


@router.post("/calls/upload", response_model=IngestAccepted, status_code=status.HTTP_201_CREATED)
async def upload_call(
    request: Request,
    principal: OperatorDep,
    session: TenantSession,
    response: Response,
    file: Annotated[UploadFile, File()],
    caller_number: Annotated[str, Form()],
    dialed_number: Annotated[str, Form()],
    asterisk_uniqueid: Annotated[str, Form()] = "",
    started_at: Annotated[datetime | None, Form()] = None,
    ended_at: Annotated[datetime | None, Form()] = None,
    direction: Annotated[str | None, Form()] = "inbound",
    agent_extension: Annotated[str | None, Form()] = None,
) -> IngestAccepted:
    """Manual WAV upload from the tenant panel; billed like agent ingest."""
    assert principal.tenant_id is not None
    await ratelimit.enforce(
        f"user-upload:{principal.id}", get_settings().rate_limit_uploads_per_minute
    )
    caller = caller_number.strip()
    dialed = dialed_number.strip()
    if not caller or not dialed:
        raise ApiError("invalid_request", "caller_number and dialed_number are required")

    resolved_extension = agent_extension.strip() if agent_extension else None
    if operator_scope.is_operator(principal):
        if not principal.extension:
            raise ApiError("forbidden", "operator extension is required for call ownership")
        resolved_extension = principal.extension

    result = await accept_upload(
        tenant_id=principal.tenant_id,
        payload=await file.read(),
        asterisk_uniqueid=asterisk_uniqueid,
        caller_number=caller,
        dialed_number=dialed,
        started_at=started_at,
        ended_at=ended_at,
        direction=direction,
        agent_extension=resolved_extension,
    )
    if result.replayed:
        response.status_code = status.HTTP_200_OK
        return result.accepted

    await audit.record(
        session,
        actor_type="user",
        actor_id=principal.id,
        tenant_id=principal.tenant_id,
        action="call.manual_upload",
        payload={"call_id": str(result.accepted.call_id)},
        ip=client_ip(request),
    )
    return result.accepted


def _summary(call: Call, insight: CallInsight | None, *, hide_billing: bool = False) -> CallSummary:
    # Tenant API never exposes provider internals (VoiceSanj, empty-transcript, keys).
    progress_pct, public_detail, processing = resolve_progress(
        call.status, call.progress_pct, call.progress_detail
    )
    updated_at = getattr(call, "updated_at", call.ended_at)
    return CallSummary(
        id=call.id,
        asterisk_uniqueid=call.asterisk_uniqueid,
        caller_number=call.caller_number,
        dialed_number=call.dialed_number,
        direction=call.direction,
        agent_extension=call.agent_extension,
        started_at=call.started_at,
        ended_at=call.ended_at,
        updated_at=updated_at,
        duration_ms=call.duration_ms,
        billed_seconds=None if hide_billing else call.billed_seconds,
        status=call.status,
        error_code=None,
        progress_pct=progress_pct,
        progress_detail=public_detail,
        processing=processing,
        recovery_pending=(
            call.status in {"emotion_queued", "transcribed"}
            and datetime.now(UTC) - updated_at > timedelta(seconds=30)
        ),
        summary=insight.summary if insight else None,
        sentiment=_sentiment(insight),
        sentiment_trajectory=_trajectory(insight),
        intent=insight.intent if insight else None,
    )


def _sentiment(insight: CallInsight | None) -> Sentiment | None:
    if insight is None or not insight.sentiment:
        return None
    try:
        mapped = normalize_sentiment(insight.sentiment)
    except ValueError:
        return None
    if mapped not in SENTIMENT_SET:
        return None
    return type_cast(Sentiment, mapped)


def _trajectory(insight: CallInsight | None) -> SentimentTrajectory | None:
    if insight is None:
        return None
    value = caller_trajectory(insight.sentiment_profile)
    if value is None:
        return None
    return value


async def _load_call(
    session: AsyncSession,
    call_id: UUID,
    tenant_id: UUID,
    principal: Principal | None = None,
) -> Call:
    call = (
        await session.execute(select(Call).where(Call.id == call_id, Call.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if call is None:
        raise ApiError("not_found", "call not found")
    if principal is not None:
        await operator_scope.assert_call_visible_canonical(session, call, principal)
    return call


@router.get("/calls/{call_id}", response_model=CallDetail)
async def get_call(call_id: UUID, principal: UserDep, session: TenantSession) -> CallDetail:
    assert principal.tenant_id is not None
    call = await _load_call(session, call_id, principal.tenant_id, principal)
    transcript = (
        await session.execute(
            select(Transcript).where(
                Transcript.call_id == call_id, Transcript.tenant_id == principal.tenant_id
            )
        )
    ).scalar_one_or_none()
    insight = (
        await session.execute(
            select(CallInsight).where(
                CallInsight.call_id == call_id, CallInsight.tenant_id == principal.tenant_id
            )
        )
    ).scalar_one_or_none()
    sales = (
        await session.execute(
            select(SalesInsight).where(
                SalesInsight.call_id == call_id,
                SalesInsight.tenant_id == principal.tenant_id,
            )
        )
    ).scalar_one_or_none()
    utterances = (
        (
            await session.execute(
                select(Utterance)
                .where(Utterance.call_id == call_id, Utterance.tenant_id == principal.tenant_id)
                .order_by(Utterance.t_start_ms, Utterance.channel)
            )
        )
        .scalars()
        .all()
    )
    latest_revision = (
        await session.execute(
            select(TranscriptRevision)
            .where(
                TranscriptRevision.call_id == call_id,
                TranscriptRevision.tenant_id == principal.tenant_id,
                TranscriptRevision.asr_revision_id
                == (transcript.active_asr_revision_id if transcript is not None else None),
            )
            .order_by(TranscriptRevision.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    corrected_segments: list[TranscriptRevisionSegment] = []
    active_asr_revision = None
    if transcript is not None and transcript.active_asr_revision_id is not None:
        active_asr_revision = await session.get(
            AsrTranscriptRevision, transcript.active_asr_revision_id
        )
    if transcript is not None and transcript.active_revision_id is not None:
        corrected_segments = list(
            (
                await session.execute(
                    select(TranscriptRevisionSegment)
                    .where(
                        TranscriptRevisionSegment.revision_id == transcript.active_revision_id,
                        TranscriptRevisionSegment.tenant_id == principal.tenant_id,
                    )
                    .order_by(TranscriptRevisionSegment.position)
                )
            ).scalars()
        )
    run = (
        await session.execute(
            select(AnalysisRun)
            .where(
                AnalysisRun.call_id == call_id,
                AnalysisRun.tenant_id == principal.tenant_id,
                AnalysisRun.status == "succeeded",
            )
            .order_by(AnalysisRun.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    audio_available = False
    if call.audio_id is not None:
        audio_available = (
            await session.execute(
                select(AudioObject.id).where(
                    AudioObject.id == call.audio_id,
                    AudioObject.tenant_id == principal.tenant_id,
                    AudioObject.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none() is not None

    event_rows = list(
        (
            await session.execute(
                select(ProcessingEvent)
                .where(
                    ProcessingEvent.call_id == call_id,
                    ProcessingEvent.tenant_id == principal.tenant_id,
                )
                .order_by(ProcessingEvent.created_at.desc(), ProcessingEvent.id.desc())
                .limit(100)
            )
        )
        .scalars()
        .all()
    )
    event_rows.reverse()
    latest_failed_job = None
    if call.status.startswith("failed"):
        latest_failed_job = (
            await session.execute(
                select(Job)
                .where(
                    Job.call_id == call_id,
                    Job.tenant_id == principal.tenant_id,
                    Job.status.in_(("failed_retryable", "failed_terminal")),
                )
                .order_by(Job.created_at.desc(), Job.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    public_events = [ProcessingEventOut.model_validate(event) for event in event_rows]
    if not public_events:
        legacy_jobs = (
            (
                await session.execute(
                    select(Job)
                    .where(Job.call_id == call_id, Job.tenant_id == principal.tenant_id)
                    .order_by(Job.created_at)
                )
            )
            .scalars()
            .all()
        )
        public_events = [
            ProcessingEventOut(
                id=job.id,
                kind=job.kind,
                level=(
                    "error"
                    if job.status == "failed_terminal"
                    else "warning"
                    if job.status == "failed_retryable"
                    else "success"
                    if job.status == "succeeded"
                    else "info"
                ),
                status=job.status,
                progress_pct=None,
                message={
                    "queued": "کار در صف پردازش قرار گرفت",
                    "running": "پردازش این مرحله شروع شد",
                    "succeeded": "این مرحله با موفقیت تمام شد",
                    "failed_retryable": "این مرحله خطا داد و برای تلاش مجدد زمان‌بندی شد",
                    "failed_terminal": "این مرحله به‌دلیل خطا متوقف شد",
                }.get(job.status, job.status),
                error_code=job.error_code,
                error_detail=processing_events.sanitize_detail(job.error_detail),
                created_at=job.created_at,
            )
            for job in legacy_jobs
        ]

    summary_payload = _summary(
        call, insight, hide_billing=operator_scope.is_operator(principal)
    ).model_dump()
    summary_payload["error_code"] = call.error_code
    task_pairs = await follow_up_tasks.list_for_call(
        session, call, insight.action_items if insight else None
    )
    return CallDetail(
        **summary_payload,
        audio_available=audio_available,
        can_retry_transcription=(
            transcript is None
            and audio_available
            and call.status == "failed_terminal"
            and latest_failed_job is not None
            and latest_failed_job.kind == "asr"
            and latest_failed_job.status == "failed_terminal"
        ),
        transcript=transcript.full_text if transcript else None,
        corrected_transcript=transcript.corrected_text if transcript else None,
        corrected_transcript_at=transcript.corrected_at if transcript else None,
        asr_model=f"{transcript.asr_model}:{transcript.asr_version}" if transcript else None,
        active_asr_revision_id=transcript.active_asr_revision_id if transcript else None,
        speaker_mode=active_asr_revision.speaker_mode if active_asr_revision else None,
        utterances=(
            [
                UtteranceOut(
                    channel=item.channel,
                    t_start_ms=item.t_start_ms,
                    t_end_ms=item.t_end_ms,
                    text=item.corrected_text,
                    source_text=item.source_text,
                    uncertain=item.uncertain,
                )
                for item in corrected_segments
            ]
            if corrected_segments
            else [UtteranceOut.model_validate(u) for u in utterances]
        ),
        raw_utterances=[UtteranceOut.model_validate(u) for u in utterances],
        speaker_labels=(
            {0: "گوینده ۱", 1: "گوینده ۲"}
            if active_asr_revision and (active_asr_revision.speaker_mode or "").startswith("mono")
            else
            {0: "مشتری", 1: "اپراتور"}
            if call.direction == "inbound"
            else {0: "اپراتور", 1: "مشتری"}
            if call.direction == "outbound"
            else {0: "کانال ۱", 1: "کانال ۲"}
        ),
        correction=(
            CorrectionStatusOut(
                id=latest_revision.id,
                status=latest_revision.status,
                trigger=latest_revision.trigger,
                mode=latest_revision.mode,
                audio_models=latest_revision.audio_models,
                text_models=latest_revision.text_models,
                provider_model=latest_revision.provider_model,
                error_code=latest_revision.error_code,
                error_detail=processing_events.sanitize_detail(latest_revision.error_detail),
                uncertain_items=latest_revision.uncertain_items or [],
                uncertain_count=int((latest_revision.metrics or {}).get("uncertain_count") or 0),
                uncertain_ratio=float((latest_revision.metrics or {}).get("uncertain_ratio") or 0),
                queued_at=latest_revision.queued_at,
                started_at=latest_revision.started_at,
                provider_submitted_at=latest_revision.provider_submitted_at,
                completed_at=latest_revision.completed_at,
            )
            if latest_revision
            else None
        ),
        insights=InsightsOut.model_validate(insight) if insight else None,
        sales=(
            SalesBlock.model_validate(
                {
                    "funnel_stage": sales.funnel_stage,
                    "outcome": sales.outcome,
                    "certainty": sales.certainty,
                    "confidence": sales.confidence,
                    "product": sales.product,
                    "objections": sales.objections,
                    "win_loss_reason": sales.win_loss_reason,
                    "next_action": sales.next_action,
                    "next_action_due_at": sales.next_action_due_at,
                    "evidence": sales.evidence,
                }
            )
            if sales
            else None
        ),
        tasks=[follow_up_tasks.serialize(task, related) for task, related in task_pairs],
        analysis_run_id=run.id if run else None,
        prompt_version=run.prompt_version if run else None,
        llm_model=run.llm_model if run else None,
        error_detail=processing_events.sanitize_detail(
            latest_failed_job.error_detail if latest_failed_job else None
        ),
        processing_events=public_events,
    )


@router.post("/calls/{call_id}/retry-transcription", status_code=status.HTTP_202_ACCEPTED)
async def retry_transcription(
    call_id: UUID, request: Request, principal: OperatorDep
) -> dict[str, str]:
    assert principal.tenant_id is not None
    tenant_id = principal.tenant_id
    job_id: UUID

    async with session_scope(tenant_id) as session:
        visible_call = await _load_call(session, call_id, tenant_id, principal)
        call = (
            await session.execute(
                select(Call)
                .where(Call.id == visible_call.id, Call.tenant_id == tenant_id)
                .with_for_update()
            )
        ).scalar_one()
        transcript = (
            await session.execute(
                select(Transcript.call_id).where(
                    Transcript.call_id == call_id,
                    Transcript.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        if transcript is not None:
            raise ApiError("invalid_request", "متن تماس قبلاً ایجاد شده است.")
        if call.status != "failed_terminal":
            raise ApiError("conflict_idempotency", "این تماس در وضعیت قابل پردازش مجدد نیست.")
        audio = (
            await session.execute(
                select(AudioObject).where(
                    AudioObject.id == call.audio_id,
                    AudioObject.tenant_id == tenant_id,
                    AudioObject.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if audio is None:
            raise ApiError("not_found", "فایل صوتی این تماس در دسترس نیست.")
        latest_asr_job = (
            await session.execute(
                select(Job)
                .where(
                    Job.call_id == call_id,
                    Job.tenant_id == tenant_id,
                    Job.kind == "asr",
                )
                .order_by(Job.created_at.desc(), Job.id.desc())
                .limit(1)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if latest_asr_job is None or latest_asr_job.status != "failed_terminal":
            raise ApiError("conflict_idempotency", "خطای نهایی تبدیل گفتار برای این تماس یافت نشد.")

        tenant = await session.get(Tenant, tenant_id)
        if tenant is None:
            raise ApiError("not_found", "tenant not found")
        await billing.reserve_retry(
            session,
            tenant=tenant,
            call_id=call_id,
            duration_ms=audio.duration_ms,
        )

        models = await effective_models(session)
        job = Job(
            tenant_id=tenant_id,
            call_id=call_id,
            kind="asr",
            status="queued",
            attempt=0,
            run_after=datetime.now(UTC),
            ai_provider=models["asr_ai_provider"],
            ai_model=capability_model(models, "asr"),
        )
        session.add(job)
        await session.flush()
        job_id = job.id
        call.status = "stored"
        call.error_code = None
        restored = progress.values_for_status("stored")
        call.progress_pct = int(restored["progress_pct"])
        call.progress_detail = "پردازش مجدد صوت در صف قرار گرفت"
        call.updated_at = datetime.now(UTC)
        await processing_events.record(
            session,
            tenant_id=tenant_id,
            call_id=call_id,
            kind="asr",
            status="queued",
            progress_pct=int(restored["progress_pct"]),
            message="پردازش مجدد صوت توسط کاربر در صف قرار گرفت",
            step_key=f"{job.id}:queued:0",
        )
        await audit.record(
            session,
            actor_type="user",
            actor_id=principal.id,
            tenant_id=tenant_id,
            action="call.retry_transcription",
            payload={
                "call_id": str(call_id),
                "job_id": str(job.id),
                "previous_job_id": str(latest_asr_job.id),
            },
            ip=client_ip(request),
        )
        outbox_id = await outbox.stage_job(
            session,
            job_id=job.id,
            tenant_id=tenant_id,
            call_id=call_id,
            kind="asr",
        )

    try:
        await outbox.dispatch_one(outbox_id)
    except Exception:
        logger.exception(
            "immediate transcription retry dispatch failed; durable dispatcher will retry",
            extra={"extra_fields": {"call_id": str(call_id), "job_id": str(job_id)}},
        )
    return {"status": "queued", "job_id": str(job_id)}


@router.post("/calls/{call_id}/retranscribe", status_code=status.HTTP_202_ACCEPTED)
async def retranscribe_call(
    call_id: UUID, request: Request, principal: OperatorDep
) -> dict[str, str]:
    assert principal.tenant_id is not None
    tenant_id = principal.tenant_id
    async with session_scope(tenant_id) as session:
        visible = await _load_call(session, call_id, tenant_id, principal)
        call = (
            await session.execute(
                select(Call)
                .where(Call.id == visible.id, Call.tenant_id == tenant_id)
                .with_for_update()
            )
        ).scalar_one()
        transcript = await session.get(Transcript, call_id)
        if transcript is None:
            raise ApiError("invalid_request", "برای این تماس هنوز نسخه متنی وجود ندارد.")
        audio = (
            await session.execute(
                select(AudioObject).where(
                    AudioObject.id == call.audio_id,
                    AudioObject.tenant_id == tenant_id,
                    AudioObject.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if audio is None:
            raise ApiError("not_found", "فایل صوتی این تماس در دسترس نیست.")
        active = (
            await session.execute(
                select(AsrTranscriptRevision.id).where(
                    AsrTranscriptRevision.call_id == call_id,
                    AsrTranscriptRevision.tenant_id == tenant_id,
                    AsrTranscriptRevision.status.in_(("queued", "running")),
                )
            )
        ).scalar_one_or_none()
        if active is not None:
            raise ApiError("conflict_idempotency", "بازپردازش دیگری برای این تماس فعال است.")
        previous_status = call.status
        models = await effective_models(session)
        revision = AsrTranscriptRevision(
            call_id=call_id,
            tenant_id=tenant_id,
            status="queued",
            trigger="manual",
            metrics={"previous_status": previous_status},
            ai_provider=models["asr_ai_provider"],
            asr_model=capability_model(models, "asr"),
        )
        session.add(revision)
        job = Job(
            tenant_id=tenant_id,
            call_id=call_id,
            kind="asr",
            status="queued",
            attempt=0,
            run_after=datetime.now(UTC),
            ai_provider=models["asr_ai_provider"],
            ai_model=capability_model(models, "asr"),
        )
        session.add(job)
        await session.flush()
        await processing_events.record(
            session,
            tenant_id=tenant_id,
            call_id=call_id,
            kind="asr",
            status="queued",
            progress_pct=5,
            message="ساخت نسخه جدید متن بدون کسر اعتبار در صف قرار گرفت",
            step_key=f"{job.id}:queued:0",
        )
        await audit.record(
            session,
            actor_type="user",
            actor_id=principal.id,
            tenant_id=tenant_id,
            action="call.retranscribe",
            payload={"call_id": str(call_id), "asr_revision_id": str(revision.id)},
            ip=client_ip(request),
        )
        outbox_id = await outbox.stage_job(
            session,
            job_id=job.id,
            tenant_id=tenant_id,
            call_id=call_id,
            kind="asr",
            recovery=True,
            retranscription=True,
            previous_status=previous_status,
            asr_revision_id=revision.id,
        )
    try:
        await outbox.dispatch_one(outbox_id)
    except Exception:
        logger.exception("immediate retranscription dispatch failed; durable dispatcher will retry")
    return {"status": "queued", "asr_revision_id": str(revision.id)}


@router.get(
    "/calls/{call_id}/transcript-versions",
    response_model=list[AsrTranscriptRevisionOut],
)
async def transcript_versions(
    call_id: UUID, principal: OperatorDep, session: TenantSession
) -> list[AsrTranscriptRevisionOut]:
    assert principal.tenant_id is not None
    await _load_call(session, call_id, principal.tenant_id, principal)
    transcript = await session.get(Transcript, call_id)
    revisions = list(
        (
            await session.execute(
                select(AsrTranscriptRevision)
                .where(
                    AsrTranscriptRevision.call_id == call_id,
                    AsrTranscriptRevision.tenant_id == principal.tenant_id,
                )
                .order_by(AsrTranscriptRevision.created_at.desc())
            )
        ).scalars()
    )
    result: list[AsrTranscriptRevisionOut] = []
    for revision in revisions:
        segments = list(
            (
                await session.execute(
                    select(AsrTranscriptRevisionSegment)
                    .where(
                        AsrTranscriptRevisionSegment.revision_id == revision.id,
                        AsrTranscriptRevisionSegment.tenant_id == principal.tenant_id,
                    )
                    .order_by(AsrTranscriptRevisionSegment.position)
                )
        ).scalars()
        )
        correction = (
            await session.execute(
                select(TranscriptRevision)
                .where(
                    TranscriptRevision.asr_revision_id == revision.id,
                    TranscriptRevision.tenant_id == principal.tenant_id,
                )
                .order_by(
                    TranscriptRevision.activated_at.desc().nullslast(),
                    TranscriptRevision.created_at.desc(),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        successful_correction = correction
        if correction is not None and correction.status != "succeeded":
            successful_correction = (
                await session.execute(
                    select(TranscriptRevision)
                    .where(
                        TranscriptRevision.asr_revision_id == revision.id,
                        TranscriptRevision.tenant_id == principal.tenant_id,
                        TranscriptRevision.status == "succeeded",
                    )
                    .order_by(TranscriptRevision.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
        corrected_segments = []
        if successful_correction is not None:
            corrected_segments = list(
                (
                    await session.execute(
                        select(TranscriptRevisionSegment)
                        .where(
                            TranscriptRevisionSegment.revision_id == successful_correction.id,
                            TranscriptRevisionSegment.tenant_id == principal.tenant_id,
                        )
                        .order_by(TranscriptRevisionSegment.position)
                    )
                ).scalars()
            )
        result.append(
            AsrTranscriptRevisionOut(
                id=revision.id,
                status=revision.status,
                trigger=revision.trigger,
                full_text=revision.full_text,
                asr_model=revision.asr_model,
                asr_version=revision.asr_version,
                speaker_mode=revision.speaker_mode,
                timestamp_source=revision.timestamp_source,
                error_code=revision.error_code,
                error_detail=processing_events.sanitize_detail(revision.error_detail),
                created_at=revision.created_at,
                completed_at=revision.completed_at,
                activated_at=revision.activated_at,
                active=bool(transcript and transcript.active_asr_revision_id == revision.id),
                correction_status=correction.status if correction is not None else None,
                utterances=[
                    UtteranceOut(
                        channel=item.channel,
                        t_start_ms=item.t_start_ms,
                        t_end_ms=item.t_end_ms,
                        text=item.text,
                    )
                    for item in segments
                ],
                corrected_utterances=[
                    UtteranceOut(
                        channel=item.channel,
                        t_start_ms=item.t_start_ms,
                        t_end_ms=item.t_end_ms,
                        text=item.corrected_text,
                        source_text=item.source_text,
                        uncertain=item.uncertain,
                    )
                    for item in corrected_segments
                ],
            )
        )
    return result


@router.post(
    "/calls/{call_id}/transcript-versions/{revision_id}/activate",
    status_code=status.HTTP_202_ACCEPTED,
)
async def activate_transcript_version(
    call_id: UUID, revision_id: UUID, request: Request, principal: OperatorDep
) -> dict[str, str]:
    assert principal.tenant_id is not None
    tenant_id = principal.tenant_id
    async with session_scope(tenant_id) as session:
        call = await _load_call(session, call_id, tenant_id, principal)
        transcript = await session.get(Transcript, call_id)
        revision = await session.get(AsrTranscriptRevision, revision_id)
        if (
            transcript is None
            or revision is None
            or revision.call_id != call_id
            or revision.tenant_id != tenant_id
        ):
            raise ApiError("not_found", "نسخه متن یافت نشد.")
        pending = (
            await session.execute(
                select(AsrTranscriptRevision.id).where(
                    AsrTranscriptRevision.call_id == call_id,
                    AsrTranscriptRevision.status.in_(("queued", "running")),
                )
            )
        ).scalar_one_or_none()
        if pending is not None:
            raise ApiError("conflict_idempotency", "بازپردازش فعال باید ابتدا تمام شود.")
        await activate_existing(session, transcript=transcript, revision=revision)
        runtime = await resolve_provider_settings(session, capability="correction")
        correction = None
        if transcript.active_revision_id is None and runtime.correction_enabled:
            correction, _job, outbox_id, _created = await create_revision(
                session,
                call=call,
                transcript=transcript,
                runtime=runtime,
                trigger="automatic",
            )
        else:
            models = await effective_models(session)
            run = AnalysisRun(
                call_id=call_id,
                tenant_id=tenant_id,
                llm_model=capability_model(models, "analysis"),
                ai_provider=models.get("analysis_provider", "aiservice"),
                decision_provider=models.get("decision_provider", "aiservice"),
                decision_model=capability_model(models, "decision"),
                prompt_version=models["prompt_version"],
                system_prompt=await effective_extract_prompt(session, models["prompt_version"]),
                status="queued",
            )
            session.add(run)
            job = Job(
                tenant_id=tenant_id,
                call_id=call_id,
                kind="llm",
                status="queued",
                attempt=0,
                ai_provider=models["analysis_provider"],
            )
            session.add(job)
            call.status = "transcribed"
            await session.flush()
            outbox_id = await outbox.stage_job(
                session,
                job_id=job.id,
                tenant_id=tenant_id,
                call_id=call_id,
                kind="llm",
                analysis_run_id=run.id,
                reanalysis=True,
                previous_status="complete",
            )
        await audit.record(
            session,
            actor_type="user",
            actor_id=principal.id,
            tenant_id=tenant_id,
            action="call.activate_transcript_version",
            payload={"call_id": str(call_id), "asr_revision_id": str(revision_id)},
            ip=client_ip(request),
        )
    try:
        await outbox.dispatch_one(outbox_id)
    except Exception:
        logger.exception("transcript activation correction dispatch failed")
    return {
        "status": correction.status if correction is not None else "queued",
        "asr_revision_id": str(revision_id),
    }


@router.delete("/calls/{call_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_call(
    call_id: UUID, request: Request, principal: OrgAdminDep, session: TenantSession
) -> None:
    """Hard-delete one call and all of its operational data, including the source audio."""
    tenant_id = principal.tenant_id
    assert tenant_id is not None
    call = await _load_call(session, call_id, tenant_id, principal)
    audio = None
    if call.audio_id is not None:
        audio = (
            await session.execute(
                select(AudioObject).where(
                    AudioObject.id == call.audio_id,
                    AudioObject.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()

    # Ledger entries remain as financial history, without retaining a deleted call reference.
    await session.execute(
        update(LedgerEntry)
        .where(LedgerEntry.tenant_id == tenant_id, LedgerEntry.call_id == call_id)
        .values(call_id=None)
    )
    await session.execute(
        delete(CreditReservation).where(
            CreditReservation.tenant_id == tenant_id,
            CreditReservation.call_id == call_id,
        )
    )
    await session.execute(
        delete(WebhookDelivery).where(
            WebhookDelivery.tenant_id == tenant_id,
            WebhookDelivery.call_id == call_id,
        )
    )
    await session.delete(call)
    await session.flush()

    if audio is not None:
        await get_storage().delete(audio.object_key)
        await session.execute(
            delete(AudioObject).where(
                AudioObject.id == audio.id,
                AudioObject.tenant_id == tenant_id,
            )
        )

    await audit.record(
        session,
        actor_type="user",
        actor_id=principal.id,
        tenant_id=tenant_id,
        action="call.delete",
        payload={"call_id": str(call_id), "audio_deleted": audio is not None},
        ip=client_ip(request),
    )


async def _available_audio(
    session: AsyncSession, call_id: UUID, tenant_id: UUID, principal: Principal
) -> AudioObject:
    call = await _load_call(session, call_id, tenant_id, principal)
    if call.audio_id is None:
        raise ApiError("not_found", "call has no stored audio")
    audio = (
        await session.execute(
            select(AudioObject).where(
                AudioObject.id == call.audio_id, AudioObject.tenant_id == tenant_id
            )
        )
    ).scalar_one_or_none()
    if audio is None or audio.deleted_at is not None:
        raise ApiError("not_found", "audio has been removed by retention")
    return audio


@router.get("/calls/{call_id}/audio")
async def get_call_audio(
    call_id: UUID, principal: OperatorDep, session: TenantSession
) -> RedirectResponse:
    """302 to a short-lived presigned URL (§11, §13)."""
    assert principal.tenant_id is not None
    audio = await _available_audio(session, call_id, principal.tenant_id, principal)
    url = await get_storage().presigned_url(
        audio.object_key, get_settings().audio_presign_ttl_seconds
    )
    return RedirectResponse(url=url, status_code=status.HTTP_302_FOUND)


@router.get("/calls/{call_id}/audio/content")
async def get_call_audio_content(
    call_id: UUID, principal: OperatorDep, session: TenantSession
) -> Response:
    """Serve audio through the authenticated API without cross-origin redirects."""
    assert principal.tenant_id is not None
    audio = await _available_audio(session, call_id, principal.tenant_id, principal)
    try:
        content = await get_storage().get(audio.object_key)
    except KeyError as exc:
        raise ApiError("not_found", "audio file is missing") from exc
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") not in ("NoSuchKey", "404", "NotFound"):
            raise
        raise ApiError("not_found", "audio file is missing") from exc
    return Response(content=content, media_type="audio/wav")


@router.post("/calls/{call_id}/correct-transcript", status_code=status.HTTP_202_ACCEPTED)
async def correct_call_transcript(
    call_id: UUID, request: Request, principal: OperatorDep
) -> dict[str, str]:
    assert principal.tenant_id is not None
    tenant_id = principal.tenant_id
    async with session_scope(tenant_id) as session:
        call = await _load_call(session, call_id, tenant_id, principal)
        transcript = (
            await session.execute(
                select(Transcript).where(
                    Transcript.call_id == call_id, Transcript.tenant_id == tenant_id
                )
            )
        ).scalar_one_or_none()
        if transcript is None:
            raise ApiError(
                "not_found",
                "متن تماس هنوز آماده نشده است؛ پس از اتمام تبدیل صوت به متن دوباره تلاش کنید.",
            )
        runtime = await resolve_provider_settings(session)
        if not runtime.correction_enabled:
            raise ApiError("invalid_request", "تصحیح هوشمند در تنظیمات ادمین غیرفعال است.")
        revision, _job, outbox_id, created = await create_revision(
            session,
            call=call,
            transcript=transcript,
            runtime=runtime,
            trigger="manual",
        )
        await audit.record(
            session,
            actor_type="user",
            actor_id=principal.id,
            tenant_id=tenant_id,
            action="call.correct_transcript",
            payload={"call_id": str(call_id), "correction_run_id": str(revision.id)},
            ip=client_ip(request),
        )
    if created:
        try:
            await outbox.dispatch_one(outbox_id)
        except Exception:
            logger.exception("immediate correction dispatch failed; durable dispatcher will retry")
    return {"status": revision.status, "correction_run_id": str(revision.id)}


@router.post("/calls/{call_id}/reanalyze", status_code=status.HTTP_202_ACCEPTED)
async def reanalyze_call(call_id: UUID, request: Request, principal: OperatorDep) -> dict[str, str]:
    """New analysis run against the current prompt; never re-billed (§11)."""
    assert principal.tenant_id is not None
    tenant_id = principal.tenant_id
    previous_status: str
    run_id: UUID

    async with session_scope(tenant_id) as session:
        call = await _load_call(session, call_id, tenant_id, principal)
        transcript = (
            await session.execute(
                select(Transcript).where(
                    Transcript.call_id == call_id, Transcript.tenant_id == tenant_id
                )
            )
        ).scalar_one_or_none()
        if transcript is None:
            raise ApiError(
                "not_found",
                "متن تماس هنوز آماده نشده است؛ پس از اتمام تبدیل صوت به متن دوباره تلاش کنید.",
            )

        active = (
            (
                await session.execute(
                    select(Job).where(
                        Job.call_id == call.id,
                        Job.tenant_id == tenant_id,
                        Job.kind == "llm",
                        Job.status.in_(("queued", "running", "failed_retryable")),
                    )
                )
            )
            .scalars()
            .first()
        )
        if active is not None:
            raise ApiError(
                "conflict_idempotency", "an analysis job is already queued for this call"
            )

        previous_status = call.status
        call.status = "analyzing"
        call.error_code = None
        analyzing = progress.values_for_status("analyzing")
        call.progress_pct = int(analyzing["progress_pct"])
        call.progress_detail = "در صف تحلیل مجدد"
        call.updated_at = datetime.now(UTC)

        models = await effective_models(session)
        run = AnalysisRun(
            call_id=call.id,
            tenant_id=call.tenant_id,
            llm_model=capability_model(models, "analysis"),
            ai_provider=models.get("analysis_provider", "aiservice"),
            decision_provider=models.get("decision_provider", "aiservice"),
            decision_model=capability_model(models, "decision"),
            prompt_version=models["prompt_version"],
            system_prompt=await effective_extract_prompt(session, models["prompt_version"]),
            status="queued",
            result={"_reanalysis": True, "_previous_status": previous_status},
        )
        session.add(run)
        job = Job(
            tenant_id=call.tenant_id,
            call_id=call.id,
            kind="llm",
            status="queued",
            attempt=0,
            ai_provider=models["analysis_provider"],
        )
        session.add(job)
        await session.flush()
        await processing_events.record(
            session,
            tenant_id=tenant_id,
            call_id=call.id,
            kind="llm",
            status="queued",
            progress_pct=int(analyzing["progress_pct"]),
            message="تحلیل مجدد در صف پردازش قرار گرفت",
            step_key=f"{job.id}:queued:0",
        )
        await audit.record(
            session,
            actor_type="user",
            actor_id=principal.id,
            tenant_id=call.tenant_id,
            action="call.reanalyze",
            payload={"call_id": str(call_id), "analysis_run_id": str(run.id)},
            ip=client_ip(request),
        )
        run_id = run.id
        outbox_id = await outbox.stage_job(
            session,
            job_id=job.id,
            tenant_id=call.tenant_id,
            call_id=call.id,
            kind="llm",
            analysis_run_id=run.id,
            reanalysis=True,
            previous_status=previous_status,
        )

    try:
        await outbox.dispatch_one(outbox_id)
    except Exception:
        logger.exception(
            "immediate reanalysis dispatch failed; durable dispatcher will retry",
            extra={"extra_fields": {"call_id": str(call_id)}},
        )
    return {"analysis_run_id": str(run_id), "status": "queued"}


@router.get("/analytics/summary", response_model=AnalyticsSummary)
async def analytics_summary(
    principal: UserDep,
    session: TenantSession,
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: Annotated[datetime | None, Query()] = None,
) -> AnalyticsSummary:
    to_date = to or datetime.now(UTC)
    from_date = from_ or (to_date - timedelta(days=30))
    assert principal.tenant_id is not None
    window = operator_scope.operator_window(
        principal,
        and_(
            Call.tenant_id == principal.tenant_id,
            Call.started_at >= from_date,
            Call.started_at <= to_date,
        ),
    )

    totals = (
        await session.execute(
            select(func.count(Call.id), func.coalesce(func.sum(Call.duration_ms), 0)).where(window)
        )
    ).one()

    # literal() so SELECT and GROUP BY compile to the same SQL; a bound
    # "unknown" becomes $1 vs $6 and Postgres rejects the grouping.
    unknown = literal("unknown")
    intent_key = func.coalesce(CallInsight.intent, unknown)
    sentiment_key = func.coalesce(CallInsight.sentiment, unknown)
    day_key = func.to_char(func.date_trunc("day", Call.started_at), text("'YYYY-MM-DD'"))

    intents = (
        await session.execute(
            select(intent_key, func.count())
            .join(Call, Call.id == CallInsight.call_id)
            .where(CallInsight.tenant_id == principal.tenant_id, window)
            .group_by(intent_key)
            .order_by(func.count().desc())
        )
    ).all()

    sentiments = (
        await session.execute(
            select(sentiment_key, func.count())
            .join(Call, Call.id == CallInsight.call_id)
            .where(CallInsight.tenant_id == principal.tenant_id, window)
            .group_by(sentiment_key)
            .order_by(func.count().desc())
        )
    ).all()

    caller_trajectories = await _profile_buckets(
        session,
        tenant_id=principal.tenant_id,
        window=window,
        path=("text", "caller", "trajectory"),
        unknown=unknown,
    )
    agent_sentiments = await _profile_buckets(
        session,
        tenant_id=principal.tenant_id,
        window=window,
        path=("text", "agent", "overall", "label"),
        unknown=unknown,
    )
    agent_trajectories = await _profile_buckets(
        session,
        tenant_id=principal.tenant_id,
        window=window,
        path=("text", "agent", "trajectory"),
        unknown=unknown,
    )

    trend_rows = (
        await session.execute(
            select(day_key, sentiment_key, func.count())
            .join(CallInsight, CallInsight.call_id == Call.id)
            .where(CallInsight.tenant_id == principal.tenant_id, window)
            .group_by(day_key, sentiment_key)
            .order_by(day_key)
        )
    ).all()

    trend: dict[str, AnalyticsTrendPoint] = {}
    for day, sentiment_value, count in trend_rows:
        point = trend.setdefault(day, AnalyticsTrendPoint(date=day))
        if sentiment_value == "angry":
            point.angry = count
        elif sentiment_value == "sad":
            point.sad = count
        elif sentiment_value == "neutral":
            point.neutral = count
        elif sentiment_value == "satisfied":
            point.satisfied = count
        elif sentiment_value == "happy":
            point.happy = count

    return AnalyticsSummary(
        from_date=from_date,
        to_date=to_date,
        total_calls=int(totals[0]),
        total_minutes=round(int(totals[1]) / 60000, 1),
        intents=[AnalyticsBucket(key=str(key), count=int(count)) for key, count in intents],
        sentiments=[AnalyticsBucket(key=str(key), count=int(count)) for key, count in sentiments],
        caller_trajectories=caller_trajectories,
        agent_sentiments=agent_sentiments,
        agent_trajectories=agent_trajectories,
        trend=list(trend.values()),
    )


async def _profile_buckets(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    window: Any,
    path: tuple[str, ...],
    unknown: Any,
) -> list[AnalyticsBucket]:
    column: Any = CallInsight.sentiment_profile
    for key in path:
        column = column[key]
    key_expr = func.coalesce(column.astext, unknown)
    rows = (
        await session.execute(
            select(key_expr, func.count())
            .join(Call, Call.id == CallInsight.call_id)
            .where(CallInsight.tenant_id == tenant_id, window)
            .group_by(key_expr)
            .order_by(func.count().desc())
        )
    ).all()
    return [
        AnalyticsBucket(key=str(key), count=int(count))
        for key, count in rows
        if str(key) not in {"unknown", "null", "None", ""}
    ]
