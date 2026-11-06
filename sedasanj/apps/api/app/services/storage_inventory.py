"""Read-only accounting for tenant storage across data and control planes."""

from __future__ import annotations

import asyncio
from contextlib import aclosing
from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import func, select, text

from app.config import get_settings
from app.db import control_session_scope, session_scope
from app.errors import ApiError
from app.models import (
    AssistantExport,
    AudioDeletion,
    AudioObject,
    OrganizationDataRun,
    Tenant,
    TenantBackup,
    TenantDatabaseRegistry,
)
from app.services.storage import get_storage

MAX_SCAN_OBJECTS = 10_000
SCAN_TIMEOUT_SECONDS = 15


class StorageUsage(BaseModel):
    measured_at: datetime
    audio_retention_days: int
    audio_bytes: int
    assistant_file_bytes: int
    archive_bytes: int
    pending_audio_cleanup_bytes: int


class StorageScan(BaseModel):
    objects: int
    complete: bool
    bytes_by_category: dict[str, int]


class RelationUsage(BaseModel):
    name: str
    heap_bytes: int
    index_bytes: int
    toast_bytes: int


class StaffStorageUsage(StorageUsage):
    database_bytes: int | None
    largest_relations: list[RelationUsage]
    database_backup_bytes: int
    duplicate_audio_candidate_bytes: int
    object_store: StorageScan | None


async def _scan_object_store(tenant_id: UUID) -> StorageScan:
    categories = {
        "media": f"{tenant_id}/",
        "assistant": f"exports/{tenant_id}/",
        "archives": f"organization-archives/{tenant_id}/",
        "database_backups": f"tenant-backups/{tenant_id}/",
    }
    sizes = dict.fromkeys(categories, 0)
    count = 0
    storage = get_storage()
    async with asyncio.timeout(SCAN_TIMEOUT_SECONDS):
        for category, prefix in categories.items():
            async with aclosing(storage.iter_sizes(prefix)) as objects:
                async for size in objects:
                    if count >= MAX_SCAN_OBJECTS:
                        return StorageScan(objects=count, complete=False, bytes_by_category=sizes)
                    sizes[category] += size
                    count += 1
    return StorageScan(objects=count, complete=True, bytes_by_category=sizes)


async def storage_usage(
    tenant_id: UUID, *, staff: bool = False, scan: bool = False
) -> StaffStorageUsage:
    now = datetime.now(UTC)
    async with control_session_scope() as session:
        tenant = await session.get(Tenant, tenant_id)
        if tenant is None or tenant.status == "deleted":
            raise ApiError("not_found", "سازمان پیدا نشد. فهرست سازمان‌ها را دوباره باز کنید.")
        retention_days = tenant.audio_retention_days
        archive_bytes = await session.scalar(
            select(func.coalesce(func.sum(OrganizationDataRun.size_bytes), 0)).where(
                OrganizationDataRun.tenant_id == tenant_id,
                OrganizationDataRun.kind.in_(("manual", "scheduled")),
                OrganizationDataRun.state == "succeeded",
                OrganizationDataRun.expires_at > now,
            )
        )
        registry = await session.get(TenantDatabaseRegistry, tenant_id) if staff else None
        dedicated = (
            get_settings().tenant_databases_enabled
            and registry is not None
            and registry.status == "ready"
        )
        backup_bytes = (
            await session.scalar(
                select(func.coalesce(func.sum(TenantBackup.size_bytes), 0)).where(
                    TenantBackup.tenant_id == tenant_id, TenantBackup.status == "succeeded"
                )
            )
            if staff
            else 0
        )

    database_bytes: int | None = None
    relations: list[RelationUsage] = []
    candidate_bytes = 0
    async with session_scope(tenant_id) as session:
        live_audio = (
            select(
                func.max(AudioObject.bytes).label("size"),
                func.min(AudioObject.bytes).label("min_size"),
                func.max(AudioObject.sha256).label("digest"),
                func.min(AudioObject.sha256).label("min_digest"),
            )
            .where(AudioObject.tenant_id == tenant_id, AudioObject.deleted_at.is_(None))
            .group_by(AudioObject.bucket, AudioObject.object_key)
            .subquery()
        )
        audio_bytes = await session.scalar(select(func.coalesce(func.sum(live_audio.c.size), 0)))
        if staff:
            matches = (
                select((live_audio.c.size * (func.count() - 1)).label("reclaimable"))
                .where(
                    live_audio.c.size == live_audio.c.min_size,
                    live_audio.c.digest == live_audio.c.min_digest,
                )
                .group_by(live_audio.c.size, live_audio.c.digest)
                .subquery()
            )
            value = await session.scalar(select(func.sum(matches.c.reclaimable)))
            candidate_bytes = int(value or 0)
        export_bytes = await session.scalar(
            select(func.coalesce(func.sum(AssistantExport.size_bytes), 0)).where(
                AssistantExport.tenant_id == tenant_id,
                AssistantExport.deleted_at.is_(None),
                AssistantExport.expires_at > now,
            )
        )
        pending_bytes = await session.scalar(
            select(func.coalesce(func.sum(AudioDeletion.bytes), 0)).where(
                AudioDeletion.tenant_id == tenant_id
            )
        )
        if dedicated:
            database_bytes = await session.scalar(
                text("SELECT pg_database_size(current_database())")
            )
            result = await session.execute(
                text("""
                SELECT c.relname AS name,
                       pg_table_size(c.oid) - coalesce(pg_total_relation_size(t.oid), 0)
                           AS heap_bytes,
                       pg_indexes_size(c.oid) AS index_bytes,
                       coalesce(pg_total_relation_size(t.oid), 0) AS toast_bytes
                FROM pg_class AS c
                JOIN pg_namespace AS n ON n.oid = c.relnamespace
                LEFT JOIN pg_class AS t ON t.oid = c.reltoastrelid
                WHERE n.nspname = 'public' AND c.relkind IN ('r', 'm')
                ORDER BY pg_total_relation_size(c.oid) DESC
                LIMIT 10
            """)
            )
            relations = [RelationUsage.model_validate(dict(row)) for row in result.mappings()]

    object_store = None
    if staff and scan:
        try:
            object_store = await _scan_object_store(tenant_id)
        except Exception as exc:
            raise ApiError(
                "org_archive_unavailable",
                "اندازه‌گیری فضای فایل‌ها ناموفق بود. دسترسی ذخیره‌سازی را بررسی و دوباره تلاش کنید.",
            ) from exc
    return StaffStorageUsage(
        measured_at=now,
        audio_retention_days=retention_days,
        audio_bytes=int(audio_bytes or 0),
        assistant_file_bytes=int(export_bytes or 0),
        archive_bytes=int(archive_bytes or 0),
        pending_audio_cleanup_bytes=int(pending_bytes or 0),
        database_bytes=database_bytes,
        largest_relations=relations,
        database_backup_bytes=int(backup_bytes or 0),
        duplicate_audio_candidate_bytes=candidate_bytes,
        object_store=object_store,
    )
