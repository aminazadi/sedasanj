from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from sqlalchemy import Table, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from app.config import get_settings
from app.db import (
    control_session_scope,
    get_engine,
    get_sessionmaker,
    invalidate_tenant_engine,
)
from app.models import (
    Base,
    Job,
    Tenant,
    TenantDatabaseRegistry,
    TenantDataMigration,
    TenantProvisioningJob,
)
from app.services.tenant_secrets import encrypt_dsn

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_CONTROL_ONLY = {
    "staff_users",
    "staff_refresh_tokens",
    "platform_settings",
    "tenant_database_registry",
    "tenant_provisioning_jobs",
    "tenant_data_migrations",
    "identity_projection_outbox",
    "tenant_backups",
    "identity_projection_state",
    "contact_leads",
}
_GLOBAL_REFERENCE = {"plans", "plan_versions"}
SCHEMA_HEAD = "0032_repair_apache_age_graph"


def database_identifiers(tenant_id: UUID) -> tuple[str, str]:
    suffix = tenant_id.hex
    return f"cbi_tenant_{suffix}", f"cbi_tenant_{suffix}_app"


def _checked_identifier(value: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError("unsafe database identifier")
    return value


def _admin_url(database: str | None = None) -> URL:
    raw = get_settings().provisioner_database_url
    if not raw:
        raise RuntimeError("provisioner database URL is not configured")
    url = make_url(raw)
    return url.set(database=database) if database else url


def _runtime_url(database: str, role: str, password: str) -> str:
    return _admin_url(database).set(username=role, password=password).render_as_string(
        hide_password=False
    )


async def _run_alembic(database_url: str) -> None:
    root = Path(__file__).resolve().parents[2]
    env = dict(os.environ)
    env["DATABASE_URL"] = database_url
    process = await asyncio.create_subprocess_exec(
        "alembic",
        "upgrade",
        "head",
        cwd=str(root),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode:
        detail = (stderr or stdout).decode("utf-8", errors="replace")[-4000:]
        raise RuntimeError(f"tenant migration failed: {detail}")


async def _database_exists(engine: AsyncEngine, database_name: str) -> bool:
    async with engine.connect() as connection:
        return bool(
            (
                await connection.execute(
                    text("SELECT 1 FROM pg_database WHERE datname = :name"),
                    {"name": database_name},
                )
            ).scalar_one_or_none()
        )


async def _verify_runtime_database(runtime_dsn: str, tenant_id: UUID) -> None:
    engine = create_async_engine(runtime_dsn, pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            identity = (
                await connection.execute(text("SELECT tenant_id FROM tenant_identity LIMIT 1"))
            ).scalar_one_or_none()
            if str(identity) != str(tenant_id):
                raise RuntimeError("tenant runtime identity check failed")
            revision = (
                await connection.execute(text("SELECT version_num FROM alembic_version LIMIT 1"))
            ).scalar_one_or_none()
            if revision != SCHEMA_HEAD:
                raise RuntimeError("tenant runtime schema revision check failed")
            extensions = set(
                (
                    await connection.execute(
                        text(
                            "SELECT extname FROM pg_extension "
                            "WHERE extname IN ('vector', 'age')"
                        )
                    )
                ).scalars()
            )
            if extensions != {"vector", "age"}:
                raise RuntimeError("tenant runtime extension check failed")
            graph = (
                await connection.execute(
                    text("SELECT 1 FROM ag_catalog.ag_graph WHERE name = 'tenant_graph'")
                )
            ).scalar_one_or_none()
            if graph is None:
                raise RuntimeError("tenant runtime graph check failed")
    finally:
        await engine.dispose()


async def provision_database(tenant_id: UUID) -> TenantDatabaseRegistry:
    settings = get_settings()
    if not settings.tenant_databases_enabled:
        raise RuntimeError("tenant databases are disabled")
    database_name, runtime_role = database_identifiers(tenant_id)
    _checked_identifier(database_name)
    _checked_identifier(runtime_role)
    password = secrets.token_urlsafe(36)
    escaped_password = password.replace("'", "''")
    admin_engine = create_async_engine(_admin_url().render_as_string(hide_password=False))
    try:
        async with admin_engine.connect() as connection:
            connection = await connection.execution_options(isolation_level="AUTOCOMMIT")
            role_exists = (
                await connection.execute(
                    text("SELECT 1 FROM pg_roles WHERE rolname = :name"), {"name": runtime_role}
                )
            ).scalar_one_or_none()
            if role_exists is None:
                await connection.execute(
                    text(
                        f"CREATE ROLE {runtime_role} LOGIN NOSUPERUSER NOCREATEDB "
                        f"NOCREATEROLE NOBYPASSRLS CONNECTION LIMIT 12 "
                        f"PASSWORD '{escaped_password}'"
                    )
                )
            else:
                await connection.execute(
                    text(f"ALTER ROLE {runtime_role} PASSWORD '{escaped_password}'")
                )
            if not await _database_exists(admin_engine, database_name):
                await connection.execute(
                    text(
                        f"CREATE DATABASE {database_name} ENCODING 'UTF8' TEMPLATE template0"
                    )
                )
            await connection.execute(text(f"REVOKE ALL ON DATABASE {database_name} FROM PUBLIC"))
            await connection.execute(
                text(f"GRANT CONNECT, TEMPORARY ON DATABASE {database_name} TO {runtime_role}")
            )
    finally:
        await admin_engine.dispose()

    target_admin_url = _admin_url(database_name).render_as_string(hide_password=False)
    target = create_async_engine(target_admin_url)
    try:
        async with target.begin() as connection:
            await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await connection.execute(text("CREATE EXTENSION IF NOT EXISTS age"))
        await _run_alembic(target_admin_url)
        async with target.begin() as connection:
            await connection.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS tenant_identity ("
                    "tenant_id uuid PRIMARY KEY, created_at timestamptz NOT NULL DEFAULT now())"
                )
            )
            await connection.execute(text("TRUNCATE tenant_identity"))
            await connection.execute(
                text("INSERT INTO tenant_identity(tenant_id) VALUES (:tenant_id)"),
                {"tenant_id": tenant_id},
            )
            graph_exists = (
                await connection.execute(
                    text("SELECT 1 FROM ag_catalog.ag_graph WHERE name = 'tenant_graph'")
                )
            ).scalar_one_or_none()
            if graph_exists is None:
                await connection.execute(text("SELECT ag_catalog.create_graph('tenant_graph')"))
            await connection.execute(text(f"GRANT USAGE ON SCHEMA public TO {runtime_role}"))
            await connection.execute(text(f"GRANT USAGE ON SCHEMA ag_catalog TO {runtime_role}"))
            await connection.execute(
                text(f"GRANT SELECT ON ag_catalog.ag_graph TO {runtime_role}")
            )
            await connection.execute(
                text(f"GRANT USAGE, CREATE ON SCHEMA tenant_graph TO {runtime_role}")
            )
            await connection.execute(
                text(
                    f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public "
                    f"TO {runtime_role}"
                )
            )
            await connection.execute(
                text(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {runtime_role}")
            )
            await connection.execute(
                text(
                    f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES "
                    f"IN SCHEMA tenant_graph TO {runtime_role}"
                )
            )
            await connection.execute(
                text(
                    f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA tenant_graph "
                    f"TO {runtime_role}"
                )
            )
            await connection.execute(
                text(
                    f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, "
                    f"UPDATE, DELETE ON TABLES TO {runtime_role}"
                )
            )
            await connection.execute(text(f"GRANT SELECT ON tenant_identity TO {runtime_role}"))
    finally:
        await target.dispose()

    runtime_dsn = _runtime_url(database_name, runtime_role, password)
    await _verify_runtime_database(runtime_dsn, tenant_id)
    async with get_sessionmaker()() as session, session.begin():
        registry = await session.get(TenantDatabaseRegistry, tenant_id)
        if registry is None:
            registry = TenantDatabaseRegistry(
                tenant_id=tenant_id,
                database_name=database_name,
                runtime_role=runtime_role,
                encrypted_dsn=encrypt_dsn(runtime_dsn),
                status="provisioning",
            )
            session.add(registry)
        else:
            registry.encrypted_dsn = encrypt_dsn(runtime_dsn)
            registry.status = "provisioning"
            registry.updated_at = datetime.now(UTC)
        await session.flush()
        return registry


async def _copy_table(
    source: AsyncSession,
    target: AsyncSession,
    table: Table,
    tenant_id: UUID,
    batch_size: int,
) -> int:
    if table.name in _CONTROL_ONLY or table.name == "alembic_version":
        return 0
    if table.name == "tenants":
        statement = select(table).where(table.c.id == tenant_id)
    elif table.name in _GLOBAL_REFERENCE:
        statement = select(table)
    elif "tenant_id" in table.c:
        statement = select(table).where(table.c.tenant_id == tenant_id)
    else:
        return 0
    copied = 0
    primary_keys = [column.name for column in table.primary_key.columns]
    if not primary_keys:
        raise RuntimeError(f"tenant table {table.name} has no primary key")
    result = await source.stream(statement.execution_options(yield_per=batch_size))
    async for partition in result.mappings().partitions(batch_size):
        values = [dict(row) for row in partition]
        if values:
            insert = pg_insert(table).values(values)
            update_values = {
                column.name: getattr(insert.excluded, column.name)
                for column in table.columns
                if column.name not in primary_keys
            }
            await target.execute(
                insert.on_conflict_do_update(
                    index_elements=[table.c[name] for name in primary_keys],
                    set_=update_values,
                )
            )
            copied += len(values)
    return copied


async def copy_tenant_data(tenant_id: UUID, database_name: str) -> dict[str, int]:
    batch_size = get_settings().tenant_migration_batch_size
    target_engine = create_async_engine(
        _admin_url(database_name).render_as_string(hide_password=False)
    )
    source_maker = get_sessionmaker()
    from sqlalchemy.ext.asyncio import async_sessionmaker

    target_maker = async_sessionmaker(target_engine, expire_on_commit=False)
    counts: dict[str, int] = {}
    try:
        async with source_maker() as source, target_maker() as target:
            await source.begin()
            await source.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
            await source.execute(text("SELECT set_config('app.staff', 'on', true)"))
            await target.begin()
            await target.execute(text("SELECT set_config('app.staff', 'on', true)"))
            for table in reversed(Base.metadata.sorted_tables):
                if (
                    table.name not in _CONTROL_ONLY
                    and table.name not in _GLOBAL_REFERENCE
                    and table.name != "tenants"
                    and "tenant_id" in table.c
                ):
                    await target.execute(
                        table.delete().where(table.c.tenant_id == tenant_id)
                    )
            for table in Base.metadata.sorted_tables:
                copied = await _copy_table(source, target, table, tenant_id, batch_size)
                if (
                    table.name == "tenants"
                    or table.name in _GLOBAL_REFERENCE
                    or (
                        table.name not in _CONTROL_ONLY
                        and "tenant_id" in table.c
                    )
                ):
                    counts[table.name] = copied
            await target.commit()
            await source.rollback()
    finally:
        await target_engine.dispose()
    return counts


async def _target_counts(tenant_id: UUID, database_name: str) -> dict[str, int]:
    engine = create_async_engine(_admin_url(database_name).render_as_string(hide_password=False))
    result: dict[str, int] = {}
    try:
        async with engine.connect() as connection:
            for table in Base.metadata.sorted_tables:
                if table.name == "tenants":
                    result[table.name] = int(
                        (
                            await connection.execute(
                                select(func.count())
                                .select_from(table)
                                .where(table.c.id == tenant_id)
                            )
                        ).scalar_one()
                    )
                elif "tenant_id" in table.c and table.name not in _CONTROL_ONLY:
                    result[table.name] = int(
                        (
                            await connection.execute(
                                select(func.count())
                                .select_from(table)
                                .where(table.c.tenant_id == tenant_id)
                            )
                        ).scalar_one()
                    )
    finally:
        await engine.dispose()
    return result


async def _database_digests(
    engine: AsyncEngine, tenant_id: UUID, table_names: set[str]
) -> dict[str, str]:
    digests: dict[str, str] = {}
    async with engine.begin() as connection:
        await connection.execute(text("SELECT set_config('app.staff', 'on', true)"))
        for table in Base.metadata.sorted_tables:
            if table.name not in table_names:
                continue
            if table.name == "tenants":
                statement = select(table).where(table.c.id == tenant_id)
            elif "tenant_id" in table.c:
                statement = select(table).where(table.c.tenant_id == tenant_id)
            else:
                continue
            primary_keys = list(table.primary_key.columns)
            if primary_keys:
                statement = statement.order_by(*primary_keys)
            digest = hashlib.sha256()
            stream = await connection.stream(statement.execution_options(yield_per=500))
            async for partition in stream.mappings().partitions(500):
                for row in partition:
                    encoded = json.dumps(
                        dict(row),
                        ensure_ascii=False,
                        sort_keys=True,
                        default=str,
                        separators=(",", ":"),
                    ).encode("utf-8")
                    digest.update(encoded)
                    digest.update(b"\n")
            digests[table.name] = digest.hexdigest()
    return digests


async def _activate_target_tenant(tenant_id: UUID, database_name: str) -> None:
    engine = create_async_engine(_admin_url(database_name).render_as_string(hide_password=False))
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text("UPDATE tenants SET status = 'active' WHERE id = :tenant_id"),
                {"tenant_id": tenant_id},
            )
    finally:
        await engine.dispose()


async def _requeue_target_jobs(tenant_id: UUID, database_name: str) -> None:
    engine = create_async_engine(_admin_url(database_name).render_as_string(hide_password=False))
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE job_outbox AS outbox "
                    "SET dispatched_at = NULL, available_at = now(), last_error = NULL "
                    "FROM jobs AS job "
                    "WHERE outbox.job_id = job.id "
                    "AND outbox.tenant_id = :tenant_id "
                    "AND job.tenant_id = :tenant_id "
                    "AND job.status IN ('queued', 'failed_retryable')"
                ),
                {"tenant_id": tenant_id},
            )
    finally:
        await engine.dispose()


async def migrate_tenant(tenant_id: UUID) -> None:
    now = datetime.now(UTC)
    async with get_sessionmaker()() as session, session.begin():
        tenant = await session.get(Tenant, tenant_id, with_for_update=True)
        if tenant is None:
            raise RuntimeError("tenant not found")
        migration = (
            await session.execute(
                select(TenantDataMigration)
                .where(TenantDataMigration.tenant_id == tenant_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if migration is None:
            migration = TenantDataMigration(tenant_id=tenant_id)
            session.add(migration)
        migration.status = "running"
        migration.phase = "provisioning_target"
        checkpoint = dict(migration.checkpoint or {})
        checkpoint.setdefault("source_tenant_status", tenant.status)
        migration.checkpoint = checkpoint
        migration.updated_at = now
        if tenant.status != "active":
            tenant.status = "provisioning"
        job = (
            await session.execute(
                select(TenantProvisioningJob)
                .where(TenantProvisioningJob.tenant_id == tenant_id)
                .order_by(TenantProvisioningJob.created_at.desc())
                .with_for_update()
                .limit(1)
            )
        ).scalar_one_or_none()
        if job is None or job.status in {"failed", "succeeded"}:
            job = TenantProvisioningJob(tenant_id=tenant_id)
            session.add(job)
        job.status = "running"
        job.step = "provisioning_target"
        job.attempt = (job.attempt or 0) + 1
        job.started_at = now
        job.error_detail = None

    registry = await provision_database(tenant_id)
    database_name = registry.database_name
    async with get_sessionmaker()() as session, session.begin():
        migration = (
            await session.execute(
                select(TenantDataMigration)
                .where(TenantDataMigration.tenant_id == tenant_id)
                .with_for_update()
            )
        ).scalar_one()
        migration.phase = "source_readonly"
        migration.source_locked_at = datetime.now(UTC)
        tenant = await session.get(Tenant, tenant_id, with_for_update=True)
        assert tenant is not None
        tenant.status = "maintenance_readonly"
        job = (
            await session.execute(
                select(TenantProvisioningJob)
                .where(TenantProvisioningJob.tenant_id == tenant_id)
                .order_by(TenantProvisioningJob.created_at.desc())
                .with_for_update()
                .limit(1)
            )
        ).scalar_one()
        job.step = "draining_jobs"

    drain_deadline = (
        asyncio.get_running_loop().time() + get_settings().tenant_migration_drain_seconds
    )
    while True:
        async with control_session_scope() as session:
            active_jobs = int(
                (
                    await session.execute(
                        select(func.count(Job.id)).where(
                            Job.tenant_id == tenant_id,
                            Job.status == "running",
                        )
                    )
                ).scalar_one()
            )
        if active_jobs == 0:
            break
        if asyncio.get_running_loop().time() >= drain_deadline:
            raise RuntimeError("tenant job drain timed out")
        await asyncio.sleep(2)
    async with get_sessionmaker()() as session, session.begin():
        job = (
            await session.execute(
                select(TenantProvisioningJob)
                .where(TenantProvisioningJob.tenant_id == tenant_id)
                .order_by(TenantProvisioningJob.created_at.desc())
                .with_for_update()
                .limit(1)
            )
        ).scalar_one()
        job.step = "copying_and_validating"

    copied = await copy_tenant_data(tenant_id, database_name)
    target_counts = await _target_counts(tenant_id, database_name)
    mismatches = {
        name: {"copied": count, "target": target_counts.get(name, 0)}
        for name, count in copied.items()
        if name not in _GLOBAL_REFERENCE and target_counts.get(name, 0) != count
    }
    if mismatches:
        raise RuntimeError(f"tenant data validation failed: {mismatches}")
    digest_tables = set(copied) - _GLOBAL_REFERENCE - {"job_outbox"}
    source_digests = await _database_digests(get_engine(), tenant_id, digest_tables)
    target_engine = create_async_engine(
        _admin_url(database_name).render_as_string(hide_password=False)
    )
    try:
        target_digests = await _database_digests(
            target_engine, tenant_id, digest_tables
        )
    finally:
        await target_engine.dispose()
    digest_mismatches = {
        name: {"source": digest, "target": target_digests.get(name)}
        for name, digest in source_digests.items()
        if target_digests.get(name) != digest
    }
    if digest_mismatches:
        raise RuntimeError(f"tenant hash validation failed: {digest_mismatches}")
    await _requeue_target_jobs(tenant_id, database_name)
    await _activate_target_tenant(tenant_id, database_name)

    async with get_sessionmaker()() as session, session.begin():
        migration = (
            await session.execute(
                select(TenantDataMigration)
                .where(TenantDataMigration.tenant_id == tenant_id)
                .with_for_update()
            )
        ).scalar_one()
        registry_row = await session.get(
            TenantDatabaseRegistry, tenant_id, with_for_update=True
        )
        tenant = await session.get(Tenant, tenant_id, with_for_update=True)
        assert registry_row is not None and tenant is not None
        migration.status = "completed"
        migration.phase = "completed"
        migration.manifest = {
            "copied": copied,
            "validated": target_counts,
            "digests": target_digests,
        }
        migration.cutover_at = datetime.now(UTC)
        migration.rollback_until = datetime.now(UTC) + timedelta(
            days=get_settings().tenant_migration_rollback_days
        )
        migration.completed_at = datetime.now(UTC)
        registry_row.status = "ready"
        registry_row.schema_revision = SCHEMA_HEAD
        registry_row.last_health_at = datetime.now(UTC)
        registry_row.activated_at = datetime.now(UTC)
        tenant.status = "active"
        job = (
            await session.execute(
                select(TenantProvisioningJob)
                .where(TenantProvisioningJob.tenant_id == tenant_id)
                .order_by(TenantProvisioningJob.created_at.desc())
                .with_for_update()
                .limit(1)
            )
        ).scalar_one()
        job.status = "succeeded"
        job.step = "completed"
        job.completed_at = datetime.now(UTC)
    await invalidate_tenant_engine(tenant_id)


async def seed_existing_migrations() -> int:
    if not get_settings().tenant_database_auto_migrate:
        return 0
    async with get_sessionmaker()() as session, session.begin():
        tenant_ids = (
            await session.execute(
                select(Tenant.id)
                .outerjoin(TenantDatabaseRegistry, TenantDatabaseRegistry.tenant_id == Tenant.id)
                .where(Tenant.status != "deleted", TenantDatabaseRegistry.tenant_id.is_(None))
            )
        ).scalars().all()
        for tenant_id in tenant_ids:
            exists = (
                await session.execute(
                    select(TenantDataMigration.id).where(TenantDataMigration.tenant_id == tenant_id)
                )
            ).scalar_one_or_none()
            if exists is None:
                session.add(TenantDataMigration(tenant_id=tenant_id))
        return len(tenant_ids)


async def run_next_migration() -> str:
    await seed_existing_migrations()
    async with get_sessionmaker()() as session, session.begin():
        row = (
            await session.execute(
                select(TenantDataMigration)
                .where(TenantDataMigration.status.in_(("pending", "retryable")))
                .order_by(TenantDataMigration.created_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
        ).scalar_one_or_none()
        if row is None:
            return "idle"
        row.status = "running"
        tenant_id = row.tenant_id
    try:
        await migrate_tenant(tenant_id)
    except Exception as exc:
        async with get_sessionmaker()() as session, session.begin():
            migration = (
                await session.execute(
                    select(TenantDataMigration)
                    .where(TenantDataMigration.tenant_id == tenant_id)
                    .with_for_update()
                )
            ).scalar_one()
            job = (
                await session.execute(
                    select(TenantProvisioningJob)
                    .where(TenantProvisioningJob.tenant_id == tenant_id)
                    .order_by(TenantProvisioningJob.created_at.desc())
                    .with_for_update()
                    .limit(1)
                )
            ).scalar_one_or_none()
            exhausted = bool(
                job and job.attempt >= get_settings().tenant_migration_max_attempts
            )
            migration.status = "failed" if exhausted else "retryable"
            migration.error_detail = str(exc)[:4000]
            if job is not None:
                job.status = "failed" if exhausted else "retryable"
                job.error_detail = str(exc)[:4000]
            tenant = await session.get(Tenant, tenant_id, with_for_update=True)
            if tenant is not None:
                source_status = str(
                    dict(migration.checkpoint or {}).get("source_tenant_status", "active")
                )
                tenant.status = (
                    "active" if source_status == "active" else "migration_failed"
                )
        raise
    return "migrated"


async def run_next_fleet_migration() -> str:
    async with get_sessionmaker()() as session, session.begin():
        registry = (
            await session.execute(
                select(TenantDatabaseRegistry)
                .where(
                    TenantDatabaseRegistry.status.in_(("ready", "maintenance")),
                    TenantDatabaseRegistry.schema_revision.is_distinct_from(SCHEMA_HEAD),
                )
                .order_by(TenantDatabaseRegistry.activated_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
        ).scalar_one_or_none()
        if registry is None:
            return "idle"
        fresh_rollout = registry.status == "ready"
        registry.status = "maintenance"
        tenant_id = registry.tenant_id
        database_name = registry.database_name
        tenant = await session.get(Tenant, tenant_id, with_for_update=True)
        if tenant is not None:
            migration = (
                await session.execute(
                    select(TenantDataMigration)
                    .where(TenantDataMigration.tenant_id == tenant_id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if migration is not None:
                checkpoint = dict(migration.checkpoint or {})
                if fresh_rollout:
                    checkpoint["fleet_source_tenant_status"] = tenant.status
                else:
                    checkpoint.setdefault("fleet_source_tenant_status", "active")
                migration.checkpoint = checkpoint
            tenant.status = "maintenance_readonly"
    await invalidate_tenant_engine(tenant_id)
    try:
        await _run_alembic(
            _admin_url(database_name).render_as_string(hide_password=False)
        )
    except Exception:
        async with get_sessionmaker()() as session, session.begin():
            registry = await session.get(
                TenantDatabaseRegistry, tenant_id, with_for_update=True
            )
            if registry is not None:
                registry.status = "failed"
        raise
    async with get_sessionmaker()() as session, session.begin():
        registry = await session.get(
            TenantDatabaseRegistry, tenant_id, with_for_update=True
        )
        if registry is not None:
            registry.status = "ready"
            registry.schema_revision = SCHEMA_HEAD
            registry.last_health_at = datetime.now(UTC)
        tenant = await session.get(Tenant, tenant_id, with_for_update=True)
        if tenant is not None:
            migration = (
                await session.execute(
                    select(TenantDataMigration).where(
                        TenantDataMigration.tenant_id == tenant_id
                    )
                )
            ).scalar_one_or_none()
            tenant.status = str(
                dict(migration.checkpoint or {}).get(
                    "fleet_source_tenant_status", "active"
                )
                if migration is not None
                else "active"
            )
    return "fleet_migrated"


async def sync_global_references() -> str:
    async with get_sessionmaker()() as control:
        database_names = list(
            (
                await control.execute(
                    select(TenantDatabaseRegistry.database_name).where(
                        TenantDatabaseRegistry.status == "ready"
                    )
                )
            ).scalars()
        )
    if not database_names:
        return "idle"
    from sqlalchemy.ext.asyncio import async_sessionmaker

    for database_name in database_names:
        engine = create_async_engine(
            _admin_url(database_name).render_as_string(hide_password=False)
        )
        target_maker = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with get_sessionmaker()() as source, target_maker() as target:
                await source.begin()
                await source.execute(text("SELECT set_config('app.staff', 'on', true)"))
                await target.begin()
                for table in Base.metadata.sorted_tables:
                    if table.name in _GLOBAL_REFERENCE:
                        await _copy_table(source, target, table, UUID(int=0), 500)
                await target.commit()
                await source.rollback()
        finally:
            await engine.dispose()
    return "synchronized"


async def rollback_tenant(tenant_id: UUID) -> None:
    async with get_sessionmaker()() as session:
        migration = (
            await session.execute(
                select(TenantDataMigration).where(TenantDataMigration.tenant_id == tenant_id)
            )
        ).scalar_one_or_none()
        registry = await session.get(TenantDatabaseRegistry, tenant_id)
        if migration is None or registry is None or migration.status != "completed":
            raise RuntimeError("completed tenant migration not found")
        if migration.rollback_until is None or migration.rollback_until < datetime.now(UTC):
            raise RuntimeError("tenant rollback window has expired")
        expected = dict(migration.manifest or {}).get("digests") or {}
        database_name = registry.database_name
    engine = create_async_engine(_admin_url(database_name).render_as_string(hide_password=False))
    try:
        current = await _database_digests(engine, tenant_id, set(expected))
    finally:
        await engine.dispose()
    changed = {
        name: {"cutover": digest, "current": current.get(name)}
        for name, digest in expected.items()
        if current.get(name) != digest
    }
    if changed:
        raise RuntimeError(
            "rollback requires reconciliation because target data changed after cutover"
        )
    async with get_sessionmaker()() as session, session.begin():
        migration = (
            await session.execute(
                select(TenantDataMigration)
                .where(TenantDataMigration.tenant_id == tenant_id)
                .with_for_update()
            )
        ).scalar_one()
        registry = await session.get(TenantDatabaseRegistry, tenant_id, with_for_update=True)
        tenant = await session.get(Tenant, tenant_id, with_for_update=True)
        assert registry is not None and tenant is not None
        registry.status = "quarantined"
        registry.quarantine_until = migration.rollback_until
        migration.status = "rolled_back"
        migration.phase = "rolled_back"
        tenant.status = "active"
    await invalidate_tenant_engine(tenant_id)
