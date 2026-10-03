from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, normalize_api_key
from app.models import (
    Call,
    Job,
    Transcript,
    TranscriptRevision,
    TranscriptRevisionSegment,
    Utterance,
)
from app.services import outbox, processing_events, progress
from app.services.provider_errors import ProviderError, classify_http, inspect_payload
from app.services.voicesanj import VOICESANJ_USER_AGENT

ACTIVE_STATUSES = ("queued", "running", "validating")
NUMBER_TOKEN = re.compile(r"[0-9۰-۹٠-٩]+(?:[./:-][0-9۰-۹٠-٩]+)*")


def profile_version(runtime: Settings) -> str:
    payload = {
        "mode": runtime.correction_mode,
        "audio_models": runtime.correction_audio_models,
        "text_models": runtime.correction_text_models,
        "prompt": runtime.correction_prompt,
        "strictness": runtime.correction_strictness,
        "uncertain_ratio": runtime.correction_max_uncertain_ratio,
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()[:16]


def revision_mode(runtime: Settings, trigger: str) -> str:
    return "text_only" if trigger == "manual" else runtime.correction_mode


def should_run_text_correction(mode: str, trigger: str) -> bool:
    return trigger == "manual" or mode != "audio_only"


def correction_model_index(revision: TranscriptRevision) -> int:
    metrics = revision.metrics or {}
    value = metrics.get("text_model_index", 0)
    return value if isinstance(value, int) and value >= 0 else 0


def current_correction_model(revision: TranscriptRevision) -> str:
    index = correction_model_index(revision)
    if index >= len(revision.text_models):
        raise ProviderError(
            "correction_provider_failed",
            "همه مدل‌های تصحیح متن ناموفق بودند.",
            retryable=False,
        )
    return revision.text_models[index]


def advance_correction_model(
    revision: TranscriptRevision, *, error: str | None = None
) -> str:
    index = correction_model_index(revision)
    failures = list((revision.metrics or {}).get("text_model_failures") or [])
    failures.append(
        {
            "model": revision.text_models[index],
            "error": (error or "model_failed")[:1000],
        }
    )
    revision.metrics = {
        **(revision.metrics or {}),
        "text_model_index": index + 1,
        "text_model_failures": failures,
    }
    revision.provider_task_id = None
    revision.provider_submitted_at = None
    return current_correction_model(revision)


async def create_revision(
    session: AsyncSession,
    *,
    call: Call,
    transcript: Transcript,
    runtime: Settings,
    trigger: str,
) -> tuple[TranscriptRevision, Job, UUID, bool]:
    existing = (
        await session.execute(
            select(TranscriptRevision)
            .where(
                TranscriptRevision.call_id == call.id,
                TranscriptRevision.tenant_id == call.tenant_id,
                TranscriptRevision.status.in_(ACTIVE_STATUSES),
            )
            .order_by(TranscriptRevision.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None:
        job = (
            await session.execute(
                select(Job)
                .where(
                    Job.call_id == call.id,
                    Job.tenant_id == call.tenant_id,
                    Job.kind == "correction",
                )
                .order_by(Job.created_at.desc())
                .limit(1)
            )
        ).scalar_one()
        return existing, job, UUID(int=0), False

    source_hash = hashlib.sha256(transcript.full_text.encode()).hexdigest()
    version = profile_version(runtime)
    identity = f"{call.id}:{source_hash}:{version}"
    if trigger == "manual":
        identity = f"{identity}:{uuid4()}"
    idempotency_key = "correction-" + hashlib.sha256(identity.encode()).hexdigest()
    previous_status = call.status
    revision = TranscriptRevision(
        call_id=call.id,
        tenant_id=call.tenant_id,
        idempotency_key=idempotency_key,
        source_sha256=source_hash,
        profile_version=version,
        trigger=trigger,
        mode=revision_mode(runtime, trigger),
        status="queued",
        audio_models=list(runtime.correction_audio_models),
        text_models=list(runtime.correction_text_models),
        raw_text=transcript.full_text,
        metrics={"previous_status": previous_status} if trigger == "manual" else {},
    )
    session.add(revision)
    job = Job(
        tenant_id=call.tenant_id,
        call_id=call.id,
        kind="correction",
        status="queued",
        attempt=0,
    )
    session.add(job)
    call.status = "correcting"
    call.error_code = None
    values = progress.values_for_status("correcting")
    call.progress_pct = int(values["progress_pct"])
    call.progress_detail = str(values["progress_detail"])
    call.updated_at = datetime.now(UTC)
    await session.flush()
    await processing_events.record(
        session,
        tenant_id=call.tenant_id,
        call_id=call.id,
        kind="correction",
        status="queued",
        progress_pct=52,
        message="تصحیح هوشمند متن در صف پردازش قرار گرفت",
        step_key=f"{job.id}:queued:0",
    )
    outbox_id = await outbox.stage_job(
        session,
        job_id=job.id,
        tenant_id=call.tenant_id,
        call_id=call.id,
        kind="correction",
        correction_run_id=revision.id,
    )
    return revision, job, outbox_id, True


def source_segments(utterances: list[Utterance]) -> list[dict[str, Any]]:
    return [
        {
            "id": str(item.id),
            "channel": item.channel,
            "t_start_ms": item.t_start_ms,
            "t_end_ms": max(item.t_end_ms, item.t_start_ms + 1),
            "text": item.text,
            "confidence": item.confidence,
            "metadata": item.metadata_json,
        }
        for item in utterances
    ]


class CorrectionClient:
    def __init__(self, runtime: Settings) -> None:
        base = (runtime.voicesanj_base_url or "").rstrip("/")
        key = normalize_api_key(runtime.voicesanj_api_key)
        if not base or not key:
            raise ProviderError(
                "correction_provider_configuration",
                "آدرس یا کلید AISERVICE برای تصحیح متن تنظیم نشده است.",
                retryable=False,
            )
        self._base = base
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=15, read=30, write=30, pool=15),
            headers={
                "Authorization": f"Bearer {key}",
                "User-Agent": VOICESANJ_USER_AGENT,
                "Accept": "application/json",
            },
            http2=False,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def submit(
        self,
        revision: TranscriptRevision,
        segments: list[dict[str, Any]],
        prompt: str,
        *,
        model: str,
    ) -> str:
        body: dict[str, Any] = {
            "model": model,
            "segments": segments,
            "operation": "correction",
            "style": "formal",
            "prompt": prompt,
        }
        response = await self._client.post(
            f"{self._base}/v1/text/process",
            headers={
                "Idempotency-Key": (
                    f"{revision.idempotency_key}-text-{correction_model_index(revision)}"
                )
            },
            json=body,
        )
        self._check(response, 202)
        payload = response.json()
        task_id = payload.get("task_id") if isinstance(payload, dict) else None
        if not isinstance(task_id, str) or not task_id:
            raise ProviderError("correction_provider_response", "شناسه کار تصحیح نامعتبر است.")
        return task_id

    async def status(self, task_id: str) -> dict[str, Any]:
        response = await self._client.get(f"{self._base}/v1/tasks/{task_id}")
        self._check(response, 200)
        payload = response.json()
        if not isinstance(payload, dict):
            raise ProviderError("correction_provider_response", "وضعیت کار تصحیح نامعتبر است.")
        inspect_payload(payload, kind="llm")
        return payload

    async def result(self, task_id: str) -> dict[str, Any]:
        response = await self._client.get(f"{self._base}/v1/tasks/{task_id}/result")
        self._check(response, 200)
        payload = response.json()
        if not isinstance(payload, dict):
            raise ProviderError("correction_provider_response", "خروجی تصحیح نامعتبر است.")
        if isinstance(payload.get("results"), list):
            successful = [row for row in payload["results"] if row.get("status") == "succeeded"]
            if not successful:
                raise ProviderError(
                    "correction_provider_failed",
                    "همه مدل‌های تصحیح ناموفق بودند.",
                    retryable=False,
                )
            payload = successful[0].get("result") or successful[0]
        return payload

    @staticmethod
    def _check(response: httpx.Response, expected: int) -> None:
        if response.status_code == expected:
            return
        classified = classify_http(response.status_code, response.text, kind="llm")
        if classified is not None:
            raise classified
        raise ProviderError(
            "correction_provider_http",
            f"AISERVICE پاسخ HTTP {response.status_code} داد.",
            retryable=response.status_code >= 500,
        )


def validate_result(
    source: list[dict[str, Any]], result: dict[str, Any], *, max_uncertain_ratio: float
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    finish_reason = result.get("finish_reason")
    if finish_reason not in (None, "stop"):
        raise ValueError(f"correction output is incomplete: {finish_reason}")
    rows = result.get("segments")
    uncertain_items = result.get("uncertain_items") or []
    if not isinstance(rows, list) or len(rows) != len(source):
        raise ValueError("correction segment count changed")
    if not isinstance(uncertain_items, list):
        raise ValueError("correction uncertain_items is invalid")
    uncertain_ids = {
        str(item.get("segment_id"))
        for item in uncertain_items
        if isinstance(item, dict) and item.get("segment_id")
    }
    validated: list[dict[str, Any]] = []
    for original, corrected in zip(source, rows, strict=True):
        if not isinstance(corrected, dict) or str(corrected.get("id")) != original["id"]:
            raise ValueError("correction segment ids or order changed")
        text = str(corrected.get("corrected_text") or "").strip()
        if not text:
            raise ValueError("correction returned an empty segment")
        is_uncertain = bool(corrected.get("uncertain")) or original["id"] in uncertain_ids
        if (
            NUMBER_TOKEN.findall(original["text"]) != NUMBER_TOKEN.findall(text)
            and not is_uncertain
        ):
            raise ValueError("critical number changed without an uncertain item")
        words = text.split()
        if len(words) >= 8 and len(set(words)) <= max(2, len(words) // 5):
            raise ValueError("correction contains abnormal repetition")
        validated.append({**original, "corrected_text": text, "uncertain": is_uncertain})
    ratio = sum(1 for item in validated if item["uncertain"]) / max(len(validated), 1)
    if ratio > max_uncertain_ratio:
        raise ValueError("correction uncertain ratio exceeds configured limit")
    normalized_uncertain = [
        item if isinstance(item, dict) else {"reason": str(item)}
        for item in uncertain_items
    ]
    return validated, normalized_uncertain


async def activate_revision(
    session: AsyncSession,
    *,
    transcript: Transcript,
    revision: TranscriptRevision,
    segments: list[dict[str, Any]],
    uncertain_items: list[dict[str, Any]],
    result: dict[str, Any],
) -> None:
    for position, item in enumerate(segments):
        session.add(
            TranscriptRevisionSegment(
                revision_id=revision.id,
                tenant_id=revision.tenant_id,
                source_utterance_id=UUID(item["id"]),
                position=position,
                channel=item["channel"],
                t_start_ms=item["t_start_ms"],
                t_end_ms=item["t_end_ms"],
                source_text=item["text"],
                corrected_text=item["corrected_text"],
                confidence=item.get("confidence"),
                uncertain=item["uncertain"],
                metadata_json=item.get("metadata"),
            )
        )
    corrected_text = "\n".join(item["corrected_text"] for item in segments)
    now = datetime.now(UTC)
    revision.status = "succeeded"
    revision.corrected_text = corrected_text
    revision.provider_model = str(result.get("model") or "") or None
    revision.uncertain_items = uncertain_items
    revision.metrics = {
        **(revision.metrics or {}),
        "usage": result.get("usage"),
        "finish_reason": result.get("finish_reason"),
    }
    revision.completed_at = now
    revision.activated_at = now
    transcript.corrected_text = corrected_text
    transcript.corrected_at = now
    transcript.active_revision_id = revision.id
