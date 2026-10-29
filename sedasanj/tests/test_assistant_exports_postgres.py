"""Run against an explicitly supplied, disposable PostgreSQL database only."""

import importlib.util
import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

TEST_DSN = os.environ.get("ASSISTANT_EXPORT_TEST_DSN")
pytestmark = pytest.mark.skipif(not TEST_DSN, reason="disposable PostgreSQL DSN not supplied")


async def test_export_migration_roundtrip_and_rls():
    path = (
        Path(__file__).resolve().parents[1] / "apps/api/alembic/versions/0061_assistant_exports.py"
    )
    spec = importlib.util.spec_from_file_location("export_migration", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_async_engine(TEST_DSN)

    def migrate(connection, direction):
        with Operations.context(MigrationContext.configure(connection)):
            getattr(migration, direction)()

    try:
        async with engine.begin() as conn:
            # The entire test, including parent fixtures and DDL, rolls back at the end.
            await conn.execute(text("CREATE ROLE cbi_app NOLOGIN"))
            for table in ("tenants", "users", "chat_conversations"):
                await conn.execute(text(f"CREATE TABLE {table} (id UUID PRIMARY KEY)"))
            await conn.run_sync(lambda sync: migrate(sync, "upgrade"))
            assert await conn.scalar(text("SELECT to_regclass('assistant_exports')"))
            policy = await conn.execute(
                text(
                    "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                    "WHERE relname = 'assistant_exports'"
                )
            )
            assert policy.one() == (True, True)
            assert await conn.scalar(
                text(
                    "SELECT has_table_privilege('cbi_app', 'assistant_exports', "
                    "'SELECT,INSERT,UPDATE,DELETE')"
                )
            )
            tenants = [uuid4(), uuid4()]
            for tenant in tenants:
                await conn.execute(text("INSERT INTO tenants VALUES (:id)"), {"id": tenant})
                await conn.execute(
                    text(
                        "INSERT INTO assistant_exports "
                        "(id, tenant_id, dataset, format, filename, storage_key, size_bytes, "
                        "row_count, expires_at) VALUES (:id, :tenant, 'transcripts', 'json', "
                        "'test.json', :key, 2, 0, now() + interval '1 hour')"
                    ),
                    {"id": uuid4(), "tenant": tenant, "key": str(uuid4())},
                )
            await conn.execute(text("SET LOCAL ROLE cbi_app"))
            await conn.execute(text("SELECT set_config('app.staff', 'off', true)"))
            await conn.execute(
                text("SELECT set_config('app.tenant_id', :id, true)"), {"id": str(tenants[0])}
            )
            assert await conn.scalar(text("SELECT count(*) FROM assistant_exports")) == 1
            assert await conn.scalar(text("SELECT tenant_id FROM assistant_exports")) == tenants[0]
            await conn.execute(text("SELECT set_config('app.tenant_id', '', true)"))
            assert await conn.scalar(text("SELECT count(*) FROM assistant_exports")) == 0
            await conn.execute(text("RESET ROLE"))
            await conn.run_sync(lambda sync: migrate(sync, "downgrade"))
            assert await conn.scalar(text("SELECT to_regclass('assistant_exports')")) is None
            await conn.run_sync(lambda sync: migrate(sync, "upgrade"))
            assert await conn.scalar(text("SELECT count(*) FROM assistant_exports")) == 0
            await conn.rollback()
    finally:
        await engine.dispose()
