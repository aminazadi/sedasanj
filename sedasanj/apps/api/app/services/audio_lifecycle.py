"""Separate logical audio retirement from retryable object-store deletion."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.db import control_session_scope, routable_tenant_ids, session_scope
from app.metrics import audio_cleanup_total
from app.models import AudioDeletion, AudioObject, Call, Meeting, MeetingChunk
from app.services.storage import get_storage

logger = logging.getLogger(__name__)
BATCH_SIZE = 25


def _lock_key(tenant_id: UUID) -> ColumnElement[int]:
    return func.hashtextextended(f"sedasanj-tenant-media:{tenant_id}", 0)


@asynccontextmanager
async def protect_tenant_media(tenant_id: UUID) -> AsyncIterator[None]:
    """Pin current tenant objects while a read snapshot is consumed."""
    async with control_session_scope() as session:
        await session.execute(select(func.pg_advisory_xact_lock_shared(_lock_key(tenant_id))))
        yield


@asynccontextmanager
async def try_media_cleanup(tenant_id: UUID) -> AsyncIterator[bool]:
    async with control_session_scope() as session:
        acquired = await session.scalar(
            select(func.pg_try_advisory_xact_lock(_lock_key(tenant_id)))
        )
        yield bool(acquired)


async def queue_delete(
    session: AsyncSession, tenant_id: UUID, bucket: str, key: str, size: int
) -> None:
    await session.execute(
        insert(AudioDeletion)
        .values(tenant_id=tenant_id, bucket=bucket, object_key=key, bytes=size)
        .on_conflict_do_nothing()
    )


async def keep_uploaded(session: AsyncSession, tenant_id: UUID, bucket: str, key: str) -> None:
    await session.execute(
        delete(AudioDeletion).where(
            AudioDeletion.tenant_id == tenant_id,
            AudioDeletion.bucket == bucket,
            AudioDeletion.object_key == key,
        )
    )


async def retire_audio(session: AsyncSession, audio: AudioObject) -> None:
    if audio.deleted_at is None:
        audio.deleted_at = datetime.now(UTC)
        await queue_delete(session, audio.tenant_id, audio.bucket, audio.object_key, audio.bytes)


def has_audio_reference(
    tenant_id: UUID, *, other_than_meeting: UUID | None = None
) -> ColumnElement[bool]:
    calls = select(Call.id).where(Call.tenant_id == tenant_id, Call.audio_id == AudioObject.id)
    meetings = select(Meeting.id).where(
        Meeting.tenant_id == tenant_id, Meeting.audio_id == AudioObject.id
    )
    chunks = select(MeetingChunk.id).where(
        MeetingChunk.tenant_id == tenant_id, MeetingChunk.audio_id == AudioObject.id
    )
    if other_than_meeting is not None:
        meetings = meetings.where(Meeting.id != other_than_meeting)
        chunks = chunks.where(MeetingChunk.meeting_id != other_than_meeting)
    return (
        calls.correlate(AudioObject).exists()
        | meetings.correlate(AudioObject).exists()
        | chunks.correlate(AudioObject).exists()
    )


async def purge_tenant(tenant_id: UUID) -> int:
    async with try_media_cleanup(tenant_id) as acquired:
        if not acquired:
            return 0
        async with session_scope(tenant_id) as session:
            return await _purge_batch(session, tenant_id)


async def _purge_batch(session: AsyncSession, tenant_id: UUID) -> int:
    now = datetime.now(UTC)
    storage = get_storage()
    rows = await session.scalars(
        select(AudioDeletion)
        .where(AudioDeletion.tenant_id == tenant_id, AudioDeletion.due_at <= now)
        .order_by(AudioDeletion.due_at, AudioDeletion.object_key)
        .limit(BATCH_SIZE)
        .with_for_update(skip_locked=True)
    )
    removed = 0
    for row in rows:
        still_live = await session.scalar(
            select(
                select(AudioObject.id)
                .where(
                    AudioObject.tenant_id == tenant_id,
                    AudioObject.bucket == row.bucket,
                    AudioObject.object_key == row.object_key,
                    AudioObject.deleted_at.is_(None),
                )
                .exists()
            )
        )
        if still_live:
            await session.delete(row)
            continue
        if row.bucket != storage.bucket or not row.object_key.startswith(f"{tenant_id}/"):
            row.due_at = now + timedelta(days=1)
            audio_cleanup_total.labels(result="invalid_location").inc()
            continue
        try:
            await storage.delete(row.object_key)
        except Exception:
            row.attempts += 1
            row.due_at = now + timedelta(minutes=2 ** min(row.attempts, 8))
            audio_cleanup_total.labels(result="storage_error").inc()
            continue
        await session.delete(row)
        removed += 1
    return removed


async def purge_audio_deletions() -> int:
    removed = 0
    for tenant_id in await routable_tenant_ids():
        try:
            removed += await purge_tenant(tenant_id)
        except Exception:
            audio_cleanup_total.labels(result="database_error").inc()
            logger.warning("Audio cleanup failed; check tenant database access")
    audio_cleanup_total.labels(result="deleted").inc(removed)
    return removed
