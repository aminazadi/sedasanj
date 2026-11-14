"""Exact AI token accounting: record what the provider reported, never an estimate.

Every AI call funnels through a few client classes. They call :func:`record_usage` with the raw
provider ``usage`` object; the tenant and call come from the logging context that every worker
already sets. A missing or partial ``usage`` is stored as ``unavailable`` rather than as zero, and
a failure to record never fails the AI work itself (it is logged and counted instead).
"""

from __future__ import annotations

import contextvars
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert

from app.db import session_scope
from app.logging import call_id_var, tenant_id_var
from app.metrics import ai_usage_events_total, ai_usage_record_failures_total
from app.models import AiUsageEvent

logger = logging.getLogger(__name__)

REPORTED = "reported"
UNAVAILABLE = "unavailable"

ai_feature_var: contextvars.ContextVar[str] = contextvars.ContextVar("ai_feature", default="llm")


@contextmanager
def ai_feature(name: str) -> Iterator[None]:
    """Label the AI calls made inside the block (analysis, correction, assistant, ...)."""
    token = ai_feature_var.set(name)
    try:
        yield
    finally:
        ai_feature_var.reset(token)


def set_ai_feature(name: str) -> None:
    """Label every AI call the current task/request makes from here on.

    Each ARQ job and each HTTP request runs in its own asyncio context, so no reset is needed.
    """
    ai_feature_var.set(name)


@dataclass(frozen=True)
class TokenUsage:
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    source: str


def _count(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return int(value) if value >= 0 else None


def extract_usage(raw: object, *, output_optional: bool = False) -> TokenUsage:
    """Read OpenAI-style (`prompt/completion`) or `input/output` counts from a provider object.

    ``output_optional`` is for embeddings, which legitimately report only input tokens.
    """
    prompt = completion = total = None
    if isinstance(raw, dict):
        prompt = _count(raw.get("prompt_tokens", raw.get("input_tokens")))
        completion = _count(raw.get("completion_tokens", raw.get("output_tokens")))
        total = _count(raw.get("total_tokens"))
    if output_optional and prompt is not None and completion is None:
        completion = 0
    if prompt is None or completion is None:
        return TokenUsage(prompt, completion, total, UNAVAILABLE)
    return TokenUsage(
        prompt, completion, total if total is not None else prompt + completion, REPORTED
    )


def usage_dict(value: object) -> dict[str, Any]:
    """`value` when it is a provider usage/hint object, else an empty dict."""
    return value if isinstance(value, dict) else {}


async def record_usage(
    raw_usage: object,
    *,
    provider: str,
    model: str | None,
    origin: str | None = None,
    feature: str | None = None,
    provider_task_id: str | None = None,
    audio_seconds: float | None = None,
    output_optional: bool = False,
    tenant_id: UUID | None = None,
    call_id: UUID | None = None,
) -> None:
    """Write one ledger row. Idempotent per provider task; never raises."""
    try:
        tenant = tenant_id or _uuid(tenant_id_var.get())
        if tenant is None:
            ai_usage_record_failures_total.labels("no_tenant").inc()
            logger.warning("ai usage not recorded: no tenant in context")
            return
        usage = extract_usage(raw_usage, output_optional=output_optional)
        values: dict[str, Any] = {
            "tenant_id": tenant,
            "feature": feature or ai_feature_var.get(),
            "provider": provider,
            "origin": origin,
            "model": model,
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "total_tokens": usage.total_tokens,
            "usage_source": usage.source,
            "audio_seconds": audio_seconds,
            "provider_task_id": provider_task_id,
            "call_id": call_id or _uuid(call_id_var.get()),
            "dedupe_key": f"{provider}:{provider_task_id}" if provider_task_id else None,
        }
        from app.services import token_quota  # local: token_quota imports entitlements

        async with session_scope(tenant) as session:
            # Serialize per tenant so the plan/top-up split below is exact under concurrency.
            await token_quota.lock_tenant(session, tenant)
            inserted = (
                await session.execute(
                    insert(AiUsageEvent)
                    .values(**values)
                    .on_conflict_do_nothing(index_elements=["dedupe_key"])
                    .returning(AiUsageEvent.id)
                )
            ).first()
            if inserted is not None and usage.total_tokens:
                await token_quota.consume_overflow(session, tenant, int(usage.total_tokens))
        ai_usage_events_total.labels(provider, usage.source).inc()
    except Exception:  # noqa: BLE001 - accounting must never fail the AI work
        ai_usage_record_failures_total.labels("write_failed").inc()
        logger.exception("ai usage could not be recorded")


def _uuid(value: object) -> UUID | None:
    try:
        return UUID(str(value)) if value else None
    except ValueError:
        return None
