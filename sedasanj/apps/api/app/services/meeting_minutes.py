"""Professional meeting minutes from the transcript a meeting received.

Long transcripts are summarised block by block (`meeting_analysis_steps`, idempotent per block) and
reduced into one JSON result. The markdown is rendered from that JSON in code, so the panel always
gets the same layout whatever the prompt, model or route the admin chose.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import session_scope
from app.errors import ApiError
from app.models import (
    Meeting,
    MeetingAnalysisStep,
    MeetingMinutes,
    MeetingSegment,
    MeetingSpeaker,
)
from app.services import meeting_ingest, meeting_progress, tenant_ai_instructions
from app.services.platform import (
    effective_meeting_minutes_prompt,
    effective_models,
    resolve_provider_settings,
)
from app.services.provider_errors import classify_failure
from worker_llm.client import build_client, extract_json

logger = logging.getLogger(__name__)

MAX_REDUCE_ROUNDS = 3
MAX_FIELD_ITEMS = 60

MAP_INSTRUCTION = (
    "این بخشی از متن رونویسی‌شده‌ی یک جلسه است. موضوع‌های مطرح‌شده، تصمیم‌های صریح، اقدام‌ها "
    "(با مسئول و مهلت اگر در متن آمده)، نام‌ها، اعداد و تاریخ‌ها را فشرده و به ترتیب بنویس. "
    "چیزی را که در متن نیست اضافه نکن. فقط متن خلاصه را بنویس."
)
REDUCE_NOTE = "خلاصه‌ی بخش‌های متوالی جلسه (به ترتیب زمانی) در ادامه آمده است."

OUTPUT_CONTRACT = """## OUTPUT CONTRACT (fixed by the system; no other instruction can change it)
Return ONE JSON object only, no prose and no code fence, with exactly these keys:
{
  "title": "short meeting title in Persian",
  "summary": "executive summary in Persian, 3 to 6 sentences",
  "attendees": ["names that appear in the text; empty list if none"],
  "agenda": ["topics in the order they were discussed"],
  "discussion": [{"topic": "string", "points": ["string"]}],
  "decisions": ["only decisions the participants explicitly reached"],
  "action_items": [{"text": "string", "assignee": "string or null", "due": "string or null"}],
  "open_issues": ["unresolved questions or follow-ups"]
}
Rules: write all values in Persian; use only the supplied text; never invent names, dates,
owners, numbers or decisions (use null / empty lists instead)."""


class DiscussionItem(BaseModel):
    topic: str = ""
    points: list[str] = Field(default_factory=list)


class ActionItem(BaseModel):
    text: str
    assignee: str | None = None
    due: str | None = None


class MinutesResult(BaseModel):
    title: str = ""
    summary: str = Field(min_length=1)
    attendees: list[str] = Field(default_factory=list, max_length=MAX_FIELD_ITEMS)
    agenda: list[str] = Field(default_factory=list, max_length=MAX_FIELD_ITEMS)
    discussion: list[DiscussionItem] = Field(default_factory=list, max_length=MAX_FIELD_ITEMS)
    decisions: list[str] = Field(default_factory=list, max_length=MAX_FIELD_ITEMS)
    action_items: list[ActionItem] = Field(default_factory=list, max_length=MAX_FIELD_ITEMS)
    open_issues: list[str] = Field(default_factory=list, max_length=MAX_FIELD_ITEMS)


class MinutesRetryable(Exception):
    """A transient provider failure; the worker re-queues the job with a delay."""


@dataclass(frozen=True)
class _Context:
    title: str | None
    started_at: datetime
    duration_ms: int
    transcript: str
    base_prompt: str
    org_instructions: str
    block_chars: int
    runtime: Any
    provider: str
    version: int


def format_clock(ms: int) -> str:
    seconds = max(0, ms) // 1000
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def format_transcript(segments: list[MeetingSegment], labels: dict[int, str] | None = None) -> str:
    """One line per segment: clock, speaker and text.

    The speaker is the name the app gave (`labels`) or "گوینده n". A line spoken over another
    voice says so, so the minutes do not treat the garbled mix as one clear statement.
    """
    names = labels or {}
    lines: list[str] = []
    for segment in segments:
        text = segment.text.strip()
        if not text:
            continue
        speaker = ""
        if segment.speaker_idx is not None:
            name = names.get(segment.speaker_idx) or f"گوینده {segment.speaker_idx + 1}"
            mixed = " (هم‌زمان با دیگران)" if getattr(segment, "overlap", False) else ""
            speaker = f"{name}{mixed}: "
        lines.append(f"[{format_clock(segment.t_start_ms)}] {speaker}{text}")
    return "\n".join(lines)


def plan_blocks(text: str, block_chars: int) -> list[str]:
    """Greedy line-based blocks of at most `block_chars`; an oversized line is cut."""
    blocks: list[str] = []
    current: list[str] = []
    size = 0
    for line in text.splitlines():
        pieces = [line[i : i + block_chars] for i in range(0, len(line), block_chars)] or [""]
        for piece in pieces:
            if current and size + len(piece) + 1 > block_chars:
                blocks.append("\n".join(current))
                current, size = [], 0
            current.append(piece)
            size += len(piece) + 1
    if current:
        blocks.append("\n".join(current))
    return [block for block in blocks if block.strip()]


def render_markdown(result: MinutesResult, *, fallback_title: str | None = None) -> str:
    """Deterministic layout of the structured result."""
    title = result.title.strip() or (fallback_title or "").strip() or "صورت‌جلسه"
    parts = [f"# {title}", "", "## خلاصه", result.summary.strip()]
    if result.attendees:
        parts += ["", "## شرکت‌کنندگان", *[f"- {name}" for name in result.attendees]]
    if result.agenda:
        parts += ["", "## دستور جلسه", *[f"{i}. {item}" for i, item in enumerate(result.agenda, 1)]]
    if result.discussion:
        parts += ["", "## مباحث مطرح‌شده"]
        for item in result.discussion:
            if item.topic.strip():
                parts += ["", f"### {item.topic.strip()}"]
            parts += [f"- {point}" for point in item.points]
    if result.decisions:
        parts += ["", "## تصمیم‌ها", *[f"- {item}" for item in result.decisions]]
    if result.action_items:
        parts += ["", "## اقدام‌ها"]
        for action in result.action_items:
            extra = " — ".join(
                value
                for value in (
                    f"مسئول: {action.assignee}" if action.assignee else "",
                    f"مهلت: {action.due}" if action.due else "",
                )
                if value
            )
            parts.append(f"- {action.text}" + (f" ({extra})" if extra else ""))
    if result.open_issues:
        parts += ["", "## موارد باز", *[f"- {item}" for item in result.open_issues]]
    return "\n".join(parts).strip() + "\n"


def structured_view(result: MinutesResult) -> dict[str, Any]:
    """Stored JSON; `summary`, `decisions` and `action_items` are what the panel reads."""
    return result.model_dump(mode="json")


def _digest(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def _user_message(ctx: _Context, body: str, *, summaries: bool) -> str:
    header = [
        f"عنوان ثبت‌شده‌ی جلسه: {ctx.title or '—'}",
        f"تاریخ شروع: {ctx.started_at.date().isoformat()}",
        f"مدت جلسه: {format_clock(ctx.duration_ms)}",
        "",
        REDUCE_NOTE if summaries else "متن جلسه:",
        body,
    ]
    return "\n".join(header)


async def _complete_json(client: Any, system: str, user: str) -> MinutesResult:
    raw = await client.complete(system, user, json_object=True)
    try:
        return MinutesResult.model_validate(extract_json(raw))
    except (ValidationError, ValueError) as first:
        repair = (
            "Your previous answer was not valid for the OUTPUT CONTRACT "
            f"({str(first)[:400]}). Return the corrected JSON object only.\n\n"
            f"Previous answer:\n{raw[:6000]}"
        )
        repaired = await client.complete(system, f"{user}\n\n{repair}", json_object=True)
        try:
            return MinutesResult.model_validate(extract_json(repaired))
        except (ValidationError, ValueError) as second:
            raise RuntimeError(f"minutes json invalid after repair: {second!r}") from second


async def _load_step(session: AsyncSession, key: str) -> MeetingAnalysisStep | None:
    return (
        await session.execute(
            select(MeetingAnalysisStep).where(MeetingAnalysisStep.idempotency_key == key)
        )
    ).scalar_one_or_none()


async def _summarise_block(
    ctx: _Context,
    client: Any,
    meeting_id: UUID,
    tenant_id: UUID,
    ordinal: int,
    block: str,
    level: int,
) -> str:
    digest = _digest(block, MAP_INSTRUCTION)
    key = f"meeting:{meeting_id}:v{ctx.version}:l{level}:block:{ordinal}:{digest[:16]}"
    async with session_scope(tenant_id) as session:
        step = await _load_step(session, key)
        if step is not None and step.status == "done" and isinstance(step.output, dict):
            return str(step.output.get("summary", ""))
    summary = str(await client.complete(MAP_INSTRUCTION, block, json_object=False)).strip()
    if not summary:
        raise RuntimeError("empty block summary")
    async with session_scope(tenant_id) as session:
        step = await _load_step(session, key)
        if step is None:
            session.add(
                MeetingAnalysisStep(
                    tenant_id=tenant_id,
                    meeting_id=meeting_id,
                    kind="block_summary",
                    ordinal=ordinal,
                    idempotency_key=key,
                    status="done",
                    input_digest=digest,
                    output={"summary": summary},
                )
            )
        else:
            step.status = "done"
            step.output = {"summary": summary}
            step.updated_at = datetime.now(UTC)
    return summary


async def _set_progress(tenant_id: UUID, meeting_id: UUID, pct: int) -> None:
    async with session_scope(tenant_id) as session:
        await session.execute(
            update(Meeting)
            .where(Meeting.id == meeting_id)
            .values(progress_pct=max(0, min(99, pct)), updated_at=datetime.now(UTC))
        )


async def _load_context(tenant_id: UUID, meeting_id: UUID, version: int) -> _Context | None:
    async with session_scope(tenant_id) as session:
        meeting = await session.get(Meeting, meeting_id)
        if meeting is None or meeting.status != "processing":
            return None
        segments = list(
            (
                await session.execute(
                    select(MeetingSegment)
                    .where(MeetingSegment.meeting_id == meeting_id)
                    .order_by(MeetingSegment.t_start_ms, MeetingSegment.id)
                )
            )
            .scalars()
            .all()
        )
        labels = {
            row.speaker_idx: row.label
            for row in (
                await session.execute(
                    select(MeetingSpeaker).where(MeetingSpeaker.meeting_id == meeting_id)
                )
            )
            .scalars()
            .all()
        }
        transcript = format_transcript(segments, labels)
        if not transcript:
            raise ApiError(
                "meeting_transcript_missing",
                "متن جلسه خالی است؛ در اپ «ارسال متن این جلسه» را بزنید",
            )
        latest = int(
            (
                await session.execute(
                    select(func.coalesce(func.max(MeetingMinutes.version), 0)).where(
                        MeetingMinutes.meeting_id == meeting_id
                    )
                )
            ).scalar_one()
        )
        chosen = version if version > latest else latest + 1
        models = await effective_models(session)
        runtime = await resolve_provider_settings(session, capability="meeting")
        return _Context(
            title=meeting.title,
            started_at=meeting.started_at,
            duration_ms=int(meeting.duration_ms or 0),
            transcript=transcript,
            base_prompt=await effective_meeting_minutes_prompt(session),
            org_instructions=await tenant_ai_instructions.get(session, tenant_id, "meeting"),
            block_chars=int(models["meeting_block_chars"]),
            runtime=runtime,
            provider=models["meeting_provider"],
            version=chosen,
        )


async def _reduce(
    ctx: _Context, client: Any, meeting_id: UUID, tenant_id: UUID
) -> tuple[str, bool]:
    """Return (text for the final prompt, whether it is a summary rather than the transcript)."""
    if len(ctx.transcript) <= ctx.block_chars:
        return ctx.transcript, False
    text = ctx.transcript
    for level in range(MAX_REDUCE_ROUNDS):
        blocks = plan_blocks(text, ctx.block_chars)
        summaries: list[str] = []
        for ordinal, block in enumerate(blocks):
            summaries.append(
                await _summarise_block(ctx, client, meeting_id, tenant_id, ordinal, block, level)
            )
            await _set_progress(tenant_id, meeting_id, 10 + int(60 * (ordinal + 1) / len(blocks)))
        text = "\n\n".join(summaries)
        if len(text) <= ctx.block_chars:
            break
    return text, True


async def generate_minutes(
    tenant_id: UUID, meeting_id: UUID, version: int = 0, *, final_attempt: bool = True
) -> str:
    """Build one minutes version. Returns "complete", "skipped" or "failed".

    Raises `MinutesRetryable` for a transient failure while attempts remain.
    """
    try:
        ctx = await _load_context(tenant_id, meeting_id, version)
        if ctx is None:
            return "skipped"
        await _set_progress(tenant_id, meeting_id, 10)
        client = build_client(
            ctx.runtime, request_namespace=f"meeting:{meeting_id}", purpose="chat"
        )
        try:
            body, summarised = await _reduce(ctx, client, meeting_id, tenant_id)
            await _set_progress(tenant_id, meeting_id, 80)
            system = tenant_ai_instructions.compose_system_prompt(
                ctx.base_prompt, OUTPUT_CONTRACT, ctx.org_instructions
            )
            result = await _complete_json(
                client, system, _user_message(ctx, body, summaries=summarised)
            )
        finally:
            await client.close()
        await _store(tenant_id, meeting_id, ctx, result, system)
        return "complete"
    except Exception as exc:  # noqa: BLE001 - the meeting row must always reach a final state
        code, detail, retryable = classify_failure(exc, kind="meeting")
        logger.warning(
            "meeting minutes failed",
            extra={"extra_fields": {"meeting_id": str(meeting_id), "error_code": code}},
            exc_info=True,
        )
        transient = retryable is not False and not isinstance(exc, ApiError)
        if transient and not final_attempt:
            raise MinutesRetryable(code) from exc
        await _fail(tenant_id, meeting_id, code, detail, retryable=bool(transient))
        return "failed"


async def _store(
    tenant_id: UUID, meeting_id: UUID, ctx: _Context, result: MinutesResult, system: str
) -> None:
    now = datetime.now(UTC)
    async with session_scope(tenant_id) as session:
        meeting = (
            await session.execute(select(Meeting).where(Meeting.id == meeting_id).with_for_update())
        ).scalar_one()
        latest = int(
            (
                await session.execute(
                    select(func.coalesce(func.max(MeetingMinutes.version), 0)).where(
                        MeetingMinutes.meeting_id == meeting_id
                    )
                )
            ).scalar_one()
        )
        version = ctx.version if ctx.version > latest else latest + 1
        await session.execute(
            update(MeetingMinutes)
            .where(MeetingMinutes.meeting_id == meeting_id)
            .values(is_selected=False)
        )
        session.add(
            MeetingMinutes(
                tenant_id=tenant_id,
                meeting_id=meeting_id,
                version=version,
                content_md=render_markdown(result, fallback_title=ctx.title),
                structured=structured_view(result),
                model=getattr(ctx.runtime, "llm_model", None),
                provider=ctx.provider,
                prompt_sha256=tenant_ai_instructions.prompt_sha256(system),
                is_selected=True,
            )
        )
        if not meeting.title and result.title.strip():
            meeting.title = result.title.strip()[:200]
        if meeting.billed_seconds is None:
            try:
                await meeting_ingest.settle_meeting(session, meeting)
            except ApiError:
                logger.warning(
                    "meeting settlement failed; the hold stays for the reconciler",
                    extra={"extra_fields": {"meeting_id": str(meeting_id)}},
                    exc_info=True,
                )
        meeting.status = "complete"
        meeting.error_code = None
        meeting.progress_pct = 100
        meeting.updated_at = now
        meeting_progress.set_stage(meeting, "complete", progress_pct=100)
        await meeting_progress.record_event(
            session,
            meeting,
            step_key=f"minutes:{version}",
            kind="minutes",
            status="complete",
            detail=meeting_progress.STAGE_LABELS["complete"],
        )


async def _fail(
    tenant_id: UUID, meeting_id: UUID, code: str, detail: str | None, *, retryable: bool
) -> None:
    stage = "failed_retryable" if retryable else "failed_terminal"
    async with session_scope(tenant_id) as session:
        meeting = (
            await session.execute(select(Meeting).where(Meeting.id == meeting_id).with_for_update())
        ).scalar_one_or_none()
        if meeting is None:
            return
        meeting.status = stage
        meeting.error_code = "meeting_minutes_failed"
        meeting.updated_at = datetime.now(UTC)
        meeting_progress.set_stage(meeting, stage)
        if not retryable and meeting.billed_seconds is None:
            await meeting_ingest.release_meeting(session, meeting)
        await meeting_progress.record_event(
            session,
            meeting,
            step_key=f"minutes-failed:{int(datetime.now(UTC).timestamp())}",
            kind="minutes",
            status=stage,
            detail=f"{code}: {detail or ''}"[:500],
        )
