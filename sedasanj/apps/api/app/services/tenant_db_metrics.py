"""Prometheus metrics for tenant database migration, backup and restore.

Counters carry only the stable error code (low cardinality); never label by tenant.
Gauges are refreshed by the workers that own the work (worker-provision and
worker-tenant-backup) and read the control database.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge
from sqlalchemy import func, select

from app.db import control_session_scope
from app.models import TenantDatabaseRegistry, TenantDataMigration, TenantRestore

MIGRATION_STATUSES = ("pending", "running", "retryable", "failed")
REGISTRY_STATUSES = ("provisioning", "ready", "maintenance", "failed", "quarantined")
RESTORE_STATUSES = ("requested", "staging", "staged", "apply_requested", "applying", "failed")

migration_failures = Counter(
    "cbi_tenant_migration_failures_total", "Tenant database migration failures", ["code"]
)
backup_failures = Counter(
    "cbi_tenant_backup_failures_total", "Tenant database backup failures", ["code"]
)
restore_failures = Counter(
    "cbi_tenant_restore_failures_total", "Tenant database restore failures", ["code"]
)
restores_applied = Counter(
    "cbi_tenant_restores_applied_total", "Tenant database restores swapped in"
)
migrations = Gauge("cbi_tenant_migrations", "Tenant data migrations by status", ["status"])
registry = Gauge("cbi_tenant_database_registry", "Tenant databases by registry status", ["status"])
restores = Gauge("cbi_tenant_restores", "Tenant restores by status", ["status"])


async def _counts(column: object, model: type, statuses: tuple[str, ...]) -> dict[str, int]:
    async with control_session_scope() as session:
        rows = (
            await session.execute(
                select(column, func.count()).select_from(model).group_by(column)  # type: ignore[call-overload]
            )
        ).all()
    found = {str(status): int(count) for status, count in rows}
    return {status: found.get(status, 0) for status in statuses}


async def refresh_migration_gauges() -> None:
    for status, count in (
        await _counts(TenantDataMigration.status, TenantDataMigration, MIGRATION_STATUSES)
    ).items():
        migrations.labels(status=status).set(count)
    for status, count in (
        await _counts(TenantDatabaseRegistry.status, TenantDatabaseRegistry, REGISTRY_STATUSES)
    ).items():
        registry.labels(status=status).set(count)


async def refresh_restore_gauges() -> None:
    for status, count in (
        await _counts(TenantRestore.status, TenantRestore, RESTORE_STATUSES)
    ).items():
        restores.labels(status=status).set(count)
