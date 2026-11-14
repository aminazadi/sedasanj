from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import secrets
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Table, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession, create_async_engine

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
from app.services.apache_age import assert_age_ready
from app.services.tenant_secrets import decrypt_dsn, encrypt_dsn

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_CONTROL_ONLY = {
    "phone_otps",
    "quick_demo_sessions",
    "staff_users",
    "staff_refresh_tokens",
    "platform_settings",
    "tenant_database_registry",
    "tenant_provisioning_jobs",
    "tenant_data_migrations",
    "identity_projection_outbox",
    "tenant_backups",
    "tenant_restores",
    "organization_backup_settings",
    "organization_data_runs",
    "identity_projection_state",
    "contact_leads",
    # Pairing codes are redeemed before the tenant is known, so only the control database sees them.
    "meeting_pairing_codes",
    # Module fleet telemetry is read and written through the control database only; copying it into
    # a tenant database would also break on the foreign key to the global module_releases table.
    "module_installations",
    "module_update_events",
    "module_diagnostics",
    # Android release catalogue for the Jalase-Negar app: platform-wide, never a tenant's data.
    "jalase_negar_releases",
    "jalase_push_settings",
    "jalase_push_installations",
    "jalase_push_campaigns",
    "jalase_push_deliveries",
    # ML model registry (speaker models etc.): platform-wide artifacts, never a tenant's data.
    "ml_model_releases",
}
_GLOBAL_REFERENCE = {"plans", "plan_versions"}


def _schema_head() -> str:
    api_root = Path(__file__).resolve().parents[2]
    config = Config(str(api_root / "alembic.ini"))
    config.set_main_option("script_location", str(api_root / "alembic"))
    heads = ScriptDirectory.from_config(config).get_heads()
    if len(heads) != 1:
        raise RuntimeError(f"tenant migrations must have exactly one head; found {len(heads)}")
    return heads[0]


SCHEMA_HEAD = _schema_head()

logger = logging.getLogger(__name__)

# Stable codes for the admin page. Each maps to (Persian message, Persian next action).
MIGRATION_ERRORS: dict[str, tuple[str, str]] = {
    "TENANT_DB_KEY_INVALID": (
        "کلید رمزنگاری دیتابیس سازمان‌ها تنظیم نشده یا کار نمی‌کند.",
        "TENANT_DATABASE_MASTER_KEY را در API و worker-provision یکسان تنظیم و سرویس را "
        "راه‌اندازی مجدد کنید، سپس «تلاش مجدد» بزنید.",
    ),
    "TENANT_DB_WORKER_STALE": (
        "worker-provision با نسخهٔ قدیمی برنامه اجرا می‌شود.",
        "worker-provision را راه‌اندازی مجدد کنید، سپس «تلاش مجدد» بزنید.",
    ),
    "TENANT_DB_PREFLIGHT": (
        "پیش‌نیازهای ساخت دیتابیس برقرار نیست (اتصال مدیر دیتابیس یا افزونه‌ها).",
        "PROVISIONER_DATABASE_URL و افزونه‌های vector و age را بررسی کنید، سپس تلاش مجدد بزنید.",
    ),
    "TENANT_DB_PLAN_CONFLICT": (
        "پلن‌های دیتابیس سازمان با پلن‌های اصلی هم‌خوان نبود.",
        "آخرین نسخهٔ برنامه را مستقر و worker-provision را راه‌اندازی مجدد کنید، سپس "
        "«تلاش مجدد» بزنید.",
    ),
    "TENANT_DB_SCHEMA_REVISION": (
        "نسخهٔ ساختار دیتابیس سازمان با نسخهٔ برنامه یکی نیست.",
        "worker-provision را راه‌اندازی مجدد کنید و «تلاش مجدد» بزنید؛ اگر تکرار شد "
        "گزارش سرور را برای مهاجرت ناموفق بررسی کنید.",
    ),
    "TENANT_DB_ALEMBIC_FAILED": (
        "اجرای مهاجرت‌های ساختار در دیتابیس سازمان ناموفق بود.",
        "گزارش worker-provision را برای مهاجرت ناموفق بررسی و پس از رفع، «تلاش مجدد» بزنید.",
    ),
    "TENANT_DB_DRAIN_TIMEOUT": (
        "کارهای در حال اجرای سازمان در مهلت تعیین‌شده تمام نشد.",
        "پس از پایان یا توقف کارهای در حال اجرا «تلاش مجدد» بزنید.",
    ),
    "TENANT_DB_VALIDATION": (
        "تعداد یا هش داده‌ها پس از کپی با مبدأ برابر نبود؛ سازمان به حالت قبل برگشت.",
        "«تلاش مجدد» بزنید؛ اگر تکرار شد گزارش worker-provision را بررسی کنید.",
    ),
    "TENANT_DB_UNKNOWN": (
        "انتقال دیتابیس سازمان با خطای ناشناخته متوقف شد.",
        "گزارش worker-provision را بررسی و سپس «تلاش مجدد» بزنید.",
    ),
}


class TenantMigrationError(RuntimeError):
    """A tenant migration failure with a stable code from ``MIGRATION_ERRORS``."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code


_SQL_BLOCK = re.compile(r"\[(?:SQL|parameters):.*?\](?=\s*(?:\[|\(Background|$))", re.DOTALL)
_BACKGROUND = re.compile(r"\(Background on this error at:.*?\)", re.DOTALL)
_DSN = re.compile(r"[a-z][a-z0-9+.-]*://\S+", re.IGNORECASE)
_PASSWORD = re.compile(r"(password\s*[=:]\s*)\S+", re.IGNORECASE)


def sanitize_error_detail(raw: str, limit: int = 500) -> str:
    """Drop SQL text, bound parameters, DSNs and passwords, then cap the length."""
    text_ = _SQL_BLOCK.sub("", raw)
    text_ = _BACKGROUND.sub("", text_)
    text_ = _DSN.sub("<dsn>", text_)
    text_ = _PASSWORD.sub(r"\1<hidden>", text_)
    text_ = " ".join(text_.split())
    return text_[:limit]


def classify_migration_error(exc: BaseException) -> tuple[str, str]:
    """Return ``(code, sanitized detail)`` for a failed tenant migration."""
    raw = str(exc)
    detail = sanitize_error_detail(raw)
    if isinstance(exc, TenantMigrationError):
        return exc.code, detail
    lowered = raw.lower()
    if "master key" in lowered or "tenant database credential" in lowered:
        return "TENANT_DB_KEY_INVALID", detail
    if "plans_code_key" in lowered or ("plan_versions" in lowered and "unique" in lowered):
        return "TENANT_DB_PLAN_CONFLICT", detail
    if "schema revision check failed" in lowered:
        return "TENANT_DB_SCHEMA_REVISION", detail
    if "tenant migration failed" in lowered:
        return "TENANT_DB_ALEMBIC_FAILED", detail
    if "drain timed out" in lowered:
        return "TENANT_DB_DRAIN_TIMEOUT", detail
    if "validation failed" in lowered:
        return "TENANT_DB_VALIDATION", detail
    return "TENANT_DB_UNKNOWN", detail


def migration_error_info(code: str | None) -> dict[str, str] | None:
    if not code:
        return None
    message, action = MIGRATION_ERRORS.get(code, MIGRATION_ERRORS["TENANT_DB_UNKNOWN"])
    return {"code": code, "message": message, "action": action}


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
    return (
        _admin_url(database)
        .set(username=role, password=password)
        .render_as_string(hide_password=False)
    )


async def _run_alembic(database_url: str) -> None:
    root = Path(__file__).resolve().parents[2]
    env = dict(os.environ)
    env["DATABASE_URL"] = database_url
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "alembic",
        "-c",
        str(root / "alembic.ini"),
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
                raise RuntimeError(
                    "tenant runtime schema revision check failed: "
                    f"expected {SCHEMA_HEAD}, found {revision or 'none'}"
                )
            await assert_age_ready(connection)
    finally:
        await engine.dispose()


async def provision_database(tenant_id: UUID) -> TenantDatabaseRegistry:
    settings = get_settings()
async def grant_database_access(connection: AsyncConnection, database: str, role: str) -> None:
    """Database-level ACL; pg_dump --no-acl does not carry it, so restores must reapply it."""
    _checked_identifier(database)
    _checked_identifier(role)
    await connection.execute(text(f"REVOKE ALL ON DATABASE {database} FROM PUBLIC"))
    await connection.execute(text(f"GRANT CONNECT, TEMPORARY ON DATABASE {database} TO {role}"))


async def grant_schema_access(connection: AsyncConnection, runtime_role: str) -> None:
    """Schema, table and sequence grants for the tenant runtime role (run inside the tenant DB)."""
    _checked_identifier(runtime_role)
    await connection.execute(text(f"GRANT USAGE ON SCHEMA public TO {runtime_role}"))
    await connection.execute(text(f"GRANT USAGE ON SCHEMA ag_catalog TO {runtime_role}"))
    await connection.execute(text(f"GRANT SELECT ON ag_catalog.ag_graph TO {runtime_role}"))
    await connection.execute(text(f"GRANT USAGE, CREATE ON SCHEMA tenant_graph TO {runtime_role}"))
    await connection.execute(
        text(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {runtime_role}"
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
        text(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA tenant_graph TO {runtime_role}")
    )
    await connection.execute(
        text(
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, "
            f"UPDATE, DELETE ON TABLES TO {runtime_role}"
        )
    )
    await connection.execute(text(f"GRANT SELECT ON tenant_identity TO {runtime_role}"))


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
                    text(f"CREATE DATABASE {database_name} ENCODING 'UTF8' TEMPLATE template0")
                )
            await grant_database_access(connection, database_name, runtime_role)
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
            await grant_schema_access(connection, runtime_role)
            await assert_age_ready(connection)
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


async def _reconcile_global_reference(source: AsyncSession, target: AsyncSession) -> None:
    """Remove target plan rows the control database does not have.

    A fresh tenant database holds plans seeded by alembic with their own random ids. Upserting
    the control plans by id on top would hit the unique ``plans.code`` constraint, so rows whose
    id is unknown to the control database are dropped first (children before parents).
    """
    for name in ("plan_versions", "plans"):
        reference = Base.metadata.tables[name]
        source_ids = list((await source.execute(select(reference.c.id))).scalars())
        await target.execute(reference.delete().where(reference.c.id.not_in(source_ids)))


async def preflight() -> None:
    """Fail fast, with a stable code, before any tenant database is touched."""
    try:
        encrypted = encrypt_dsn("postgresql://preflight")
        if decrypt_dsn(encrypted) != "postgresql://preflight":
            raise RuntimeError("round trip mismatch")
    except Exception as exc:
        raise TenantMigrationError(
            "TENANT_DB_KEY_INVALID", "tenant database master key preflight failed"
        ) from exc
    on_disk = _schema_head()
    if on_disk != SCHEMA_HEAD:
        raise TenantMigrationError(
            "TENANT_DB_WORKER_STALE",
            f"worker runs schema head {SCHEMA_HEAD} but migrations on disk end at {on_disk}",
        )
    engine = create_async_engine(_admin_url().render_as_string(hide_password=False))
    try:
        async with engine.connect() as connection:
            available = set(
                (
                    await connection.execute(
                        text(
                            "SELECT name FROM pg_available_extensions "
                            "WHERE name IN ('vector', 'age')"
                        )
                    )
                ).scalars()
            )
    except Exception as exc:
        raise TenantMigrationError(
            "TENANT_DB_PREFLIGHT", "provisioner database is not reachable"
        ) from exc
    finally:
        await engine.dispose()
    missing = {"vector", "age"} - available
    if missing:
        raise TenantMigrationError(
            "TENANT_DB_PREFLIGHT", f"missing postgres extensions: {', '.join(sorted(missing))}"
        )


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
                    await target.execute(table.delete().where(table.c.tenant_id == tenant_id))
            await _reconcile_global_reference(source, target)
            for table in Base.metadata.sorted_tables:
                copied = await _copy_table(source, target, table, tenant_id, batch_size)
                if (
                    table.name == "tenants"
                    or table.name in _GLOBAL_REFERENCE
                    or (table.name not in _CONTROL_ONLY and "tenant_id" in table.c)
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

    await preflight()
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
        target_digests = await _database_digests(target_engine, tenant_id, digest_tables)
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
        registry_row = await session.get(TenantDatabaseRegistry, tenant_id, with_for_update=True)
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
            (
                await session.execute(
                    select(Tenant.id)
                    .outerjoin(
                        TenantDatabaseRegistry, TenantDatabaseRegistry.tenant_id == Tenant.id
                    )
                    .where(Tenant.status != "deleted", TenantDatabaseRegistry.tenant_id.is_(None))
                )
            )
            .scalars()
            .all()
        )
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
            exhausted = bool(job and job.attempt >= get_settings().tenant_migration_max_attempts)
            code, detail = classify_migration_error(exc)
            logger.error(
                "tenant database migration failed tenant_id=%s code=%s detail=%s",
                tenant_id,
                code,
                detail,
            )
            migration.status = "failed" if exhausted else "retryable"
            migration.error_code = code
            migration.error_detail = detail
            if job is not None:
                job.status = "failed" if exhausted else "retryable"
                job.error_code = code
                job.error_detail = detail
            tenant = await session.get(Tenant, tenant_id, with_for_update=True)
            if tenant is not None:
                source_status = str(
                    dict(migration.checkpoint or {}).get("source_tenant_status", "active")
                )
                tenant.status = "active" if source_status == "active" else "migration_failed"
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
        await _run_alembic(_admin_url(database_name).render_as_string(hide_password=False))
    except Exception:
        async with get_sessionmaker()() as session, session.begin():
            registry = await session.get(TenantDatabaseRegistry, tenant_id, with_for_update=True)
            if registry is not None:
                registry.status = "failed"
        raise
    async with get_sessionmaker()() as session, session.begin():
        registry = await session.get(TenantDatabaseRegistry, tenant_id, with_for_update=True)
        if registry is not None:
            registry.status = "ready"
            registry.schema_revision = SCHEMA_HEAD
            registry.last_health_at = datetime.now(UTC)
        tenant = await session.get(Tenant, tenant_id, with_for_update=True)
        if tenant is not None:
            migration = (
                await session.execute(
                    select(TenantDataMigration).where(TenantDataMigration.tenant_id == tenant_id)
                )
            ).scalar_one_or_none()
            tenant.status = str(
                dict(migration.checkpoint or {}).get("fleet_source_tenant_status", "active")
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
                await _reconcile_global_reference(source, target)
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
