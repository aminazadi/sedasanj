from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import session_scope
from app.metrics import outbox_dispatch_seconds, outbox_oldest_seconds, outbox_pending
from app.models import JobOutbox, Tenant, TenantDatabaseRegistry
from app.services import queue

logger = logging.getLogger(__name__)


def payload_for_job(
    kind: str,
    call_id: UUID,
    *,
    analysis_run_id: UUID | None = None,
    event: str | None = None,
    recovery: bool = False,
    reanalysis: bool = False,
    previous_status: str | None = None,
) -> tuple[str, str, dict[str, Any]]:
    if kind == "asr":
        return queue.QUEUE_ASR, queue.JOB_ASR, {
            "call_id": str(call_id),
            "recovery": recovery,
        }
    if kind == "emotion":
        if analysis_run_id is None:
            raise ValueError("emotion job requires analysis_run_id")
        return queue.QUEUE_EMOTION, queue.JOB_EMOTION, {
            "call_id": str(call_id),
            "analysis_run_id": str(analysis_run_id),
            "recovery": recovery,
        }
    if kind == "llm":
        return queue.QUEUE_LLM, queue.JOB_LLM, {
            "call_id": str(call_id),
            "analysis_run_id": str(analysis_run_id) if analysis_run_id else None,
            "reanalysis": reanalysis,
            "previous_status": previous_status,
            "recovery": recovery,
        }
    if kind == "notify":
        return queue.QUEUE_NOTIFY, queue.JOB_NOTIFY, {
            "call_id": str(call_id),
            "event": event or "call.complete",
        }
    raise ValueError(f"unsupported job kind: {kind}")


async def stage_job(
    session: AsyncSession,
    *,
    job_id: UUID,
    tenant_id: UUID,
    call_id: UUID,
    kind: str,
    analysis_run_id: UUID | None = None,
    event: str | None = None,
    recovery: bool = False,
    reanalysis: bool = False,
    previous_status: str | None = None,
    available_at: datetime | None = None,
) -> UUID:
    queue_name, function_name, payload = payload_for_job(
        kind,
        call_id,
        analysis_run_id=analysis_run_id,
        event=event,
        recovery=recovery,
        reanalysis=reanalysis,
        previous_status=previous_status,
    )
    payload["tenant_id"] = str(tenant_id)
    return await stage(
        session,
        tenant_id=tenant_id,
        job_id=job_id,
        queue_name=queue_name,
        function_name=function_name,
        payload=payload,
        available_at=available_at,
    )


async def stage(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    queue_name: str,
    function_name: str,
    payload: dict[str, Any],
    job_id: UUID | None = None,
    available_at: datetime | None = None,
) -> UUID:
    row = JobOutbox(
        tenant_id=tenant_id,
        job_id=job_id,
        queue_name=queue_name,
        function_name=function_name,
        payload=payload,
        available_at=available_at or datetime.now(UTC),
    )
    session.add(row)
    await session.flush()
    return row.id


async def _ready_tenant_ids(*, active_only: bool = True) -> list[UUID]:
    async with session_scope(None, staff=True) as session:
        statement = (
            select(TenantDatabaseRegistry.tenant_id)
            .join(Tenant, Tenant.id == TenantDatabaseRegistry.tenant_id)
            .where(TenantDatabaseRegistry.status == "ready")
        )
        if active_only:
            statement = statement.where(Tenant.status == "active")
        return list(
            (await session.execute(statement)).scalars()
        )


async def dispatch_one(outbox_id: UUID, tenant_id: UUID | None = None) -> bool:
    candidates: list[UUID | None] = [tenant_id] if tenant_id is not None else [None]
    ready_ids: list[UUID] = []
    if tenant_id is None:
        ready_ids = await _ready_tenant_ids()
        candidates.extend(ready_ids)
    for candidate in candidates:
        async with session_scope(candidate, staff=candidate is None) as session:
            statement = (
                select(JobOutbox)
                .join(Tenant, Tenant.id == JobOutbox.tenant_id)
                .where(
                    JobOutbox.id == outbox_id,
                    Tenant.status == "active",
                )
                .with_for_update(skip_locked=True)
            )
            if candidate is None and ready_ids:
                statement = statement.where(JobOutbox.tenant_id.not_in(ready_ids))
            row = (
                await session.execute(statement)
            ).scalar_one_or_none()
            if row is None:
                continue
            if row.dispatched_at is not None or row.available_at > datetime.now(UTC):
                return False
            try:
                await queue.enqueue_raw(
                    row.queue_name,
                    row.function_name,
                    dict(row.payload),
                    job_id=f"outbox:{row.id}",
                )
            except Exception as exc:
                row.attempts += 1
                row.last_error = repr(exc)[:2000]
                logger.exception(
                    "outbox dispatch failed", extra={"extra_fields": {"id": str(row.id)}}
                )
                return False
            row.dispatched_at = datetime.now(UTC)
            row.attempts += 1
            row.last_error = None
            outbox_dispatch_seconds.observe(
                max((row.dispatched_at - row.created_at).total_seconds(), 0.0)
            )
            return True
    return False


async def dispatch_pending(*, limit: int = 100) -> int:
    now = datetime.now(UTC)
    ready_ids = await _ready_tenant_ids()
    claimed: list[tuple[UUID, UUID | None]] = []
    async with session_scope(None, staff=True) as session:
        active_ids = list(
            (
                await session.execute(
                    select(Tenant.id).where(Tenant.status == "active")
                )
            ).scalars()
        )
        id_statement = (
            select(JobOutbox.id)
            .where(
                JobOutbox.dispatched_at.is_(None),
                JobOutbox.available_at <= now,
                JobOutbox.tenant_id.in_(active_ids),
            )
            .order_by(JobOutbox.available_at, JobOutbox.created_at)
            .limit(limit)
        )
        if ready_ids:
            id_statement = id_statement.where(JobOutbox.tenant_id.not_in(ready_ids))
        claimed.extend(
            (outbox_id, None)
            for outbox_id in (
                await session.execute(id_statement)
            ).scalars()
        )
    for tenant_id in ready_ids:
        if len(claimed) >= limit:
            break
        async with session_scope(tenant_id) as session:
            ids = list(
                (
                    await session.execute(
                        select(JobOutbox.id)
                        .where(
                            JobOutbox.dispatched_at.is_(None),
                            JobOutbox.available_at <= now,
                        )
                        .order_by(JobOutbox.available_at, JobOutbox.created_at)
                        .limit(limit - len(claimed))
                    )
                ).scalars()
            )
            claimed.extend((outbox_id, tenant_id) for outbox_id in ids)
    delivered = 0
    for outbox_id, target_tenant_id in claimed:
        delivered += int(await dispatch_one(outbox_id, target_tenant_id))
    pending_dates: list[datetime] = []
    async with session_scope(None, staff=True) as session:
        date_statement = select(JobOutbox.created_at).where(
            JobOutbox.dispatched_at.is_(None),
            JobOutbox.available_at <= datetime.now(UTC),
            JobOutbox.tenant_id.in_(active_ids),
        )
        if ready_ids:
            date_statement = date_statement.where(JobOutbox.tenant_id.not_in(ready_ids))
        pending_dates.extend((await session.execute(date_statement)).scalars().all())
    for tenant_id in ready_ids:
        async with session_scope(tenant_id) as session:
            pending_dates.extend(
                (
                    await session.execute(
                        select(JobOutbox.created_at).where(
                            JobOutbox.dispatched_at.is_(None),
                            JobOutbox.available_at <= datetime.now(UTC),
                        )
                    )
                ).scalars().all()
            )
    outbox_pending.set(len(pending_dates))
    oldest = min(pending_dates) if pending_dates else None
    outbox_oldest_seconds.set(
        max((datetime.now(UTC) - oldest).total_seconds(), 0.0) if oldest else 0.0
    )
    return delivered


async def purge_dispatched(*, retention_days: int = 7) -> int:
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    ready_ids = await _ready_tenant_ids(active_only=False)
    removed = 0
    async with session_scope(None, staff=True) as session:
        statement = select(JobOutbox.id).where(
            JobOutbox.dispatched_at.is_not(None),
            JobOutbox.dispatched_at < cutoff,
        )
        if ready_ids:
            statement = statement.where(JobOutbox.tenant_id.not_in(ready_ids))
        ids = list((await session.execute(statement)).scalars())
        if ids:
            await session.execute(delete(JobOutbox).where(JobOutbox.id.in_(ids)))
            removed += len(ids)
    for tenant_id in ready_ids:
        async with session_scope(tenant_id) as session:
            ids = list(
                (
                    await session.execute(
                        select(JobOutbox.id).where(
                            JobOutbox.dispatched_at.is_not(None),
                            JobOutbox.dispatched_at < cutoff,
                        )
                    )
                ).scalars()
            )
            if ids:
                await session.execute(delete(JobOutbox).where(JobOutbox.id.in_(ids)))
                removed += len(ids)
    return removed
