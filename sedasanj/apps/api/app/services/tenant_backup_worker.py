from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime

from prometheus_client import Counter, Gauge, Histogram
from sqlalchemy import func, select

from app.config import get_settings
from app.db import control_session_scope, dispose_engine
from app.logging import configure_logging
from app.metrics import start_metrics_server
from app.models import TenantBackup, TenantDatabaseRegistry
from app.services import tenant_db_metrics, tenant_restores
from app.services.tenant_backups import backup_next_due, purge_expired

logger = logging.getLogger(__name__)
attempts = Counter("cbi_tenant_backup_attempts_total", "Tenant backup attempts", ["result"])
duration = Histogram(
    "cbi_tenant_backup_seconds",
    "Tenant backup duration",
    buckets=(10, 30, 60, 180, 600, 1800, 3600, 7200),
)
overdue = Gauge("cbi_tenant_backups_overdue", "Ready tenant databases without a recent backup")


async def _update_overdue() -> None:
    latest = (
        select(func.max(TenantBackup.completed_at))
        .where(
            TenantBackup.tenant_id == TenantDatabaseRegistry.tenant_id,
            TenantBackup.status == "succeeded",
        )
        .scalar_subquery()
    )
    cutoff = (
        datetime.now(UTC).timestamp() - (get_settings().tenant_backup_interval_hours + 1) * 3600
    )
    async with control_session_scope() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(TenantDatabaseRegistry)
            .where(
                TenantDatabaseRegistry.status == "ready",
                (latest.is_(None) | (latest < datetime.fromtimestamp(cutoff, UTC))),
            )
        )
    overdue.set(count or 0)


async def main() -> None:
    settings = get_settings()
    configure_logging("worker-tenant-backup", settings.log_level)
    start_metrics_server(settings)
    try:
        while True:
            if not (settings.tenant_databases_enabled and settings.tenant_backup_enabled):
                await asyncio.sleep(60)
                continue
            started = time.monotonic()
            try:
                await _update_overdue()
                await tenant_db_metrics.refresh_restore_gauges()
                async with asyncio.timeout(7200):
                    result = await backup_next_due()
                if result == "backed_up":
                    attempts.labels(result="succeeded").inc()
                    duration.observe(time.monotonic() - started)
                await purge_expired()
                await tenant_restores.stage_next()
                await tenant_restores.apply_next()
                await tenant_restores.cleanup()
            except Exception:
                attempts.labels(result="failed").inc()
                logger.error("tenant backup worker failed; check database and backup storage")
            await asyncio.sleep(60)
    finally:
        await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
