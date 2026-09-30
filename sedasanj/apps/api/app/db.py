import logging
import time
from collections import OrderedDict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings
from app.services.tenant_secrets import decrypt_dsn

logger = logging.getLogger(__name__)

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None
_tenant_engines: OrderedDict[UUID, tuple[AsyncEngine, float, str]] = OrderedDict()
_tenant_lock: Any = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url,
            pool_size=10,
            max_overflow=10,
            pool_pre_ping=True,
        )
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _sessionmaker


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    for tenant_engine, _, _ in _tenant_engines.values():
        await tenant_engine.dispose()
    _tenant_engines.clear()
    _engine = None
    _sessionmaker = None


def _lock() -> Any:
    global _tenant_lock
    if _tenant_lock is None:
        import asyncio

        _tenant_lock = asyncio.Lock()
    return _tenant_lock


async def _tenant_engine(tenant_id: UUID) -> AsyncEngine | None:
    settings = get_settings()
    if not settings.tenant_databases_enabled:
        return None
    now = time.monotonic()
    cached = _tenant_engines.get(tenant_id)
    if cached is not None:
        engine, _, database_name = cached
        _tenant_engines[tenant_id] = (engine, now, database_name)
        _tenant_engines.move_to_end(tenant_id)
        return engine
    async with _lock():
        cached = _tenant_engines.get(tenant_id)
        if cached is not None:
            engine, _, database_name = cached
            _tenant_engines[tenant_id] = (engine, now, database_name)
            _tenant_engines.move_to_end(tenant_id)
            return engine
        async with get_sessionmaker()() as control:
            row = (
                await control.execute(
                    text(
                        "SELECT r.encrypted_dsn, r.database_name, r.schema_revision, "
                        "r.status, t.status "
                        "FROM tenant_database_registry r "
                        "JOIN tenants t ON t.id = r.tenant_id "
                        "WHERE r.tenant_id = :tenant_id"
                    ),
                    {"tenant_id": tenant_id},
                )
            ).one_or_none()
        if row is None:
            return None
        registry_status = str(row[3])
        tenant_status = str(row[4])
        if registry_status == "quarantined":
            return None
        if registry_status == "provisioning" and tenant_status == "active":
            return None
        if registry_status != "ready":
            raise RuntimeError("tenant database is not ready")
        dsn, database_name = decrypt_dsn(str(row[0])), str(row[1])
        expected_revision = str(row[2]) if row[2] else None
        engine = create_async_engine(
            dsn,
            pool_size=settings.tenant_database_pool_size,
            max_overflow=0,
            pool_pre_ping=True,
            pool_recycle=settings.tenant_database_pool_idle_seconds,
        )
        async with engine.connect() as connection:
            identity = (
                await connection.execute(text("SELECT tenant_id FROM tenant_identity LIMIT 1"))
            ).scalar_one_or_none()
            if str(identity) != str(tenant_id):
                await engine.dispose()
                raise RuntimeError("tenant database identity mismatch")
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
                await engine.dispose()
                raise RuntimeError("tenant database extensions are incomplete")
            revision = (
                await connection.execute(text("SELECT version_num FROM alembic_version LIMIT 1"))
            ).scalar_one_or_none()
            if expected_revision is not None and revision != expected_revision:
                await engine.dispose()
                raise RuntimeError("tenant database schema revision mismatch")
        _tenant_engines[tenant_id] = (engine, now, database_name)
        while len(_tenant_engines) > settings.tenant_database_max_pools:
            _, (old_engine, _, _) = _tenant_engines.popitem(last=False)
            await old_engine.dispose()
        return engine


async def invalidate_tenant_engine(tenant_id: UUID) -> None:
    cached = _tenant_engines.pop(tenant_id, None)
    if cached is not None:
        await cached[0].dispose()


async def operational_tenant_ids() -> list[UUID]:
    async with get_sessionmaker()() as session:
        rows = await session.execute(
            text("SELECT id FROM tenants WHERE status = 'active' ORDER BY created_at")
        )
        return [UUID(str(value)) for value in rows.scalars()]


async def routable_tenant_ids() -> list[UUID]:
    async with get_sessionmaker()() as session:
        rows = await session.execute(
            text(
                "SELECT id FROM tenants WHERE status IN ('active', 'suspended') "
                "ORDER BY created_at"
            )
        )
        return [UUID(str(value)) for value in rows.scalars()]


async def resolve_tenant_for_call(
    call_id: UUID, hinted_tenant_id: UUID | None = None
) -> UUID | None:
    candidates = [hinted_tenant_id] if hinted_tenant_id is not None else await routable_tenant_ids()
    for tenant_id in candidates:
        async with session_scope(tenant_id) as session:
            found = (
                await session.execute(
                    text("SELECT 1 FROM calls WHERE id = :call_id AND tenant_id = :tenant_id"),
                    {"call_id": call_id, "tenant_id": tenant_id},
                )
            ).scalar_one_or_none()
            if found is not None:
                return tenant_id
    return None


async def resolve_tenant_for_job(job_id: UUID) -> UUID | None:
    for tenant_id in await routable_tenant_ids():
        async with session_scope(tenant_id) as session:
            found = (
                await session.execute(
                    text("SELECT 1 FROM jobs WHERE id = :job_id AND tenant_id = :tenant_id"),
                    {"job_id": job_id, "tenant_id": tenant_id},
                )
            ).scalar_one_or_none()
            if found is not None:
                return tenant_id
    return None


@asynccontextmanager
async def control_session_scope() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as session:
        await session.begin()
        try:
            await apply_rls_context(session, None, staff=True)
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise


async def apply_rls_context(
    session: AsyncSession, tenant_id: UUID | None, *, staff: bool = False
) -> None:
    """Bind the RLS guards for the current transaction (§7.2)."""
    await session.execute(
        text("SELECT set_config('app.tenant_id', :tenant, true)"),
        {"tenant": str(tenant_id) if tenant_id else ""},
    )
    await session.execute(
        text("SELECT set_config('app.staff', :staff, true)"),
        {"staff": "on" if staff else "off"},
    )


@asynccontextmanager
async def session_scope(
    tenant_id: UUID | None = None, *, staff: bool = False
) -> AsyncIterator[AsyncSession]:
    """Transactional session with RLS context applied; commits on clean exit."""
    engine = await _tenant_engine(tenant_id) if tenant_id is not None and not staff else None
    maker = (
        async_sessionmaker(engine, expire_on_commit=False)
        if engine is not None
        else get_sessionmaker()
    )
    async with maker() as session:
        await session.begin()
        try:
            await apply_rls_context(session, tenant_id, staff=staff)
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise


async def assert_rls_enforced() -> None:
    """A superuser or BYPASSRLS role silently disables every tenant policy (§7.2, §12)."""
    async with get_sessionmaker()() as session:
        row = (
            await session.execute(
                text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
            )
        ).one_or_none()
    if row is None:
        return
    superuser, bypass = bool(row[0]), bool(row[1])
    if not (superuser or bypass):
        return
    message = "the application database role bypasses row level security"
    if get_settings().environment == "production":
        raise RuntimeError(message)
    logger.warning(message)


async def ping() -> dict[str, Any]:
    async with get_sessionmaker()() as session:
        await session.execute(text("SELECT 1"))
    return {"postgres": "ok"}
