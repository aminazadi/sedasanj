from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import event, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine as _create_async_engine

from app.services import tenant_backup_format, tenant_backup_restore, tenant_backups
from app.services.apache_age import AGE_GRAPH_REPAIR_SQL
from app.services.tenant_backups import BACKUP_ERRORS, backup_error_info, classify_backup_error


def create_async_engine(*args: Any, **kwargs: Any) -> Any:
    """Engine that loads Apache AGE on connect, like a server with shared_preload_libraries=age.

    The disposable test server does not preload it; production and compose do.
    """
    engine = _create_async_engine(*args, **kwargs)

    @event.listens_for(engine.sync_engine, "connect")
    def _load_age(dbapi_connection: Any, _record: Any) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("LOAD 'age'")
        except Exception:
            pass  # extension not created yet in this database
        finally:
            cursor.close()

    return engine


ROOT = Path(__file__).resolve().parents[1]
ADMIN_URL = os.environ.get("TENANT_BACKUP_TEST_URL")
needs_postgres = pytest.mark.skipif(
    not ADMIN_URL or not shutil.which("pg_dump") or not shutil.which("pg_restore"),
    reason="disposable PostgreSQL with pgvector and Apache AGE not supplied "
    "(set TENANT_BACKUP_TEST_URL, e.g. postgresql+asyncpg://postgres:pw@127.0.0.1:55433/postgres)",
)


@pytest.mark.parametrize(
    ("message", "phase", "code"),
    [
        ("configure the tenant backup recovery key", "dump", "TENANT_BACKUP_KEY_MISSING"),
        ("backup exceeds the size limit", "dump", "TENANT_BACKUP_TOO_LARGE"),
        ("pg_dump failed; check database access: boom", "dump", "TENANT_BACKUP_DUMP_FAILED"),
        ("pg_restore rejected the dump", "dump", "TENANT_BACKUP_DUMP_INVALID"),
        ("uploaded backup checksum differs", "upload", "TENANT_BACKUP_UPLOAD_FAILED"),
        ("connection reset", "upload", "TENANT_BACKUP_UPLOAD_FAILED"),
        ("something else", "dump", "TENANT_BACKUP_UNKNOWN"),
    ],
)
def test_classify_backup_error(message: str, phase: str, code: str) -> None:
    got, detail = classify_backup_error(RuntimeError(message), phase)
    assert got == code
    assert code in BACKUP_ERRORS
    assert "[SQL:" not in detail


def test_every_backup_error_code_names_an_action() -> None:
    for code, (message, action) in BACKUP_ERRORS.items():
        assert message and action, code
        info = backup_error_info(code)
        assert info is not None and info["code"] == code
    assert backup_error_info(None) is None


def test_shell_restore_carries_the_same_age_repair_as_python() -> None:
    script = (ROOT / "scripts" / "backup_lib.sh").read_text()
    for line in AGE_GRAPH_REPAIR_SQL.splitlines():
        assert line in script, line
    assert 'repair_age_graphs "${fresh}"' in script


@pytest.fixture
async def servers(monkeypatch: pytest.MonkeyPatch) -> Any:
    assert ADMIN_URL
    base = make_url(ADMIN_URL)

    def admin_url(database: str | None = None) -> Any:
        return base.set(database=database) if database else base

    monkeypatch.setattr(tenant_backup_restore, "create_async_engine", create_async_engine)
    monkeypatch.setattr(tenant_backup_restore, "_admin_url", admin_url)
    monkeypatch.setattr("app.services.tenant_provisioning._admin_url", admin_url)
    monkeypatch.setattr(
        tenant_backup_restore,
        "get_settings",
        lambda: SimpleNamespace(
            tenant_database_master_key="test-key", tenant_backup_max_bytes=1024**3
        ),
    )
    created: list[str] = []
    engine = create_async_engine(base, isolation_level="AUTOCOMMIT")
    yield SimpleNamespace(base=base, admin_url=admin_url, engine=engine, created=created)
    async with engine.connect() as connection:
        for name in created:
            await connection.execute(text(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)"))
    await engine.dispose()


async def _build_source(servers: Any, tenant: uuid.UUID) -> str:
    name = f"cbi_backup_src_{uuid.uuid4().hex[:12]}"
    servers.created.append(name)
    async with servers.engine.connect() as connection:
        await connection.execute(text(f"CREATE DATABASE {name} TEMPLATE template0"))
    source = create_async_engine(servers.admin_url(name))
    try:
        async with source.begin() as connection:
            for statement in (
                "CREATE EXTENSION vector",
                "CREATE EXTENSION age",
                "CREATE TABLE tenant_identity (tenant_id uuid PRIMARY KEY)",
                "CREATE TABLE alembic_version (version_num varchar PRIMARY KEY)",
                "INSERT INTO alembic_version VALUES ('0134_test')",
                "CREATE TABLE audio_objects (object_key text, deleted_at timestamptz, "
                "expires_at timestamptz)",
                "CREATE TABLE assistant_exports (storage_key text, deleted_at timestamptz, "
                "expires_at timestamptz)",
                "CREATE TABLE embeddings (id int PRIMARY KEY, v vector(3))",
                "INSERT INTO embeddings VALUES (1, '[1,2,3]')",
                "SELECT ag_catalog.create_graph('tenant_graph')",
            ):
                await connection.execute(text(statement))
            await connection.execute(
                text("INSERT INTO tenant_identity VALUES (:tenant)"), {"tenant": tenant}
            )
            await connection.execute(text("SET search_path = ag_catalog, public"))
            await connection.execute(
                text(
                    "SELECT * FROM cypher('tenant_graph', $$ CREATE (\\:Person {name: 'a'}) $$) "
                    "AS (x agtype)"
                )
            )
    finally:
        await source.dispose()
    return name


async def _graph_names(servers: Any, database: str) -> list[str]:
    engine = create_async_engine(servers.admin_url(database))
    try:
        async with engine.begin() as connection:
            await connection.execute(text("SET search_path = ag_catalog, public"))
            rows = await connection.execute(
                text(
                    "SELECT * FROM cypher('tenant_graph', $$ MATCH (n\\:Person) RETURN n.name $$) "
                    "AS (name agtype)"
                )
            )
            return [str(row[0]) for row in rows]
    finally:
        await engine.dispose()


@needs_postgres
async def test_backup_round_trip_restores_data_vectors_and_graph(
    servers: Any, tmp_path: Path
) -> None:
    tenant = uuid.uuid4()
    source = await _build_source(servers, tenant)
    dump, archive = tmp_path / "tenant.dump", tmp_path / "tenant.gzip"

    await tenant_backups._dump(source, dump, 1024**3, modern=True)
    await tenant_backups.verify_dump(dump)
    tenant_backup_format.seal(dump, archive, "test-key", 1024**3)

    class _Storage:
        async def exists(self, _key: str) -> bool:
            return True

    restored = f"cbi_restore_{uuid.uuid4().hex}"
    servers.created.append(restored)
    import app.services.tenant_backup_restore as restore_module

    original = restore_module.get_storage
    restore_module.get_storage = lambda: _Storage()  # type: ignore[assignment]
    try:
        await tenant_backup_restore._stage_file(archive, tenant, "0134_test", restored)
    finally:
        restore_module.get_storage = original  # type: ignore[assignment]

    assert await _graph_names(servers, restored) == ['"a"']
    engine = create_async_engine(servers.admin_url(restored))
    try:
        async with engine.connect() as connection:
            assert await connection.scalar(text("SELECT count(*) FROM embeddings")) == 1
    finally:
        await engine.dispose()


@needs_postgres
async def test_age_repair_is_idempotent_and_needed_after_a_plain_restore(
    servers: Any, tmp_path: Path
) -> None:
    tenant = uuid.uuid4()
    source = await _build_source(servers, tenant)
    dump = tmp_path / "tenant.dump"
    await tenant_backups._dump(source, dump, 1024**3, modern=True)
    restored = f"cbi_restore_{uuid.uuid4().hex}"
    servers.created.append(restored)
    await tenant_backup_restore._run_pg(
        "createdb", "--template=template0", restored, database=restored
    )
    await tenant_backup_restore._run_pg(
        "pg_restore",
        "--exit-on-error",
        "--single-transaction",
        "--no-owner",
        "--no-acl",
        "--dbname",
        restored,
        str(dump),
        database=restored,
    )
    with pytest.raises(Exception, match="graph with oid"):
        await _graph_names(servers, restored)
    await tenant_backup_restore._repair_age(restored)
    await tenant_backup_restore._repair_age(restored)
    assert await _graph_names(servers, restored) == ['"a"']


def test_restore_error_codes_have_actions_and_sanitized_details() -> None:
    from app.services import tenant_restores as tr

    for code, (message, action) in tr.RESTORE_ERRORS.items():
        assert message and action, code
        info = tr.restore_error_info(code)
        assert info is not None and info["code"] == code
    assert tr.restore_error_info(None) is None
    code, detail = tr.classify_restore_error(
        tenant_backup_format.InvalidBackup("bad [SQL: SELECT 1] [parameters: (1,)]")
    )
    assert code == "TENANT_RESTORE_BACKUP_INVALID"
    assert "SELECT" not in detail
    assert tr.classify_restore_error(RuntimeError("x"))[0] == "TENANT_RESTORE_UNKNOWN"
    assert (
        tr.classify_restore_error(tr.TenantRestoreError("TENANT_RESTORE_NOT_READY", "x"))[0]
        == "TENANT_RESTORE_NOT_READY"
    )


@pytest.mark.parametrize("name", ["cbi_tenant_x", "postgres", "cbi_restore_ABC", "cbi_restore_1"])
async def test_only_staging_databases_can_be_dropped(name: str) -> None:
    from app.services import tenant_restores as tr

    with pytest.raises(ValueError):
        await tr._drop_database(name)


@needs_postgres
async def test_swap_replaces_the_live_database_and_undo_restores_it(servers: Any) -> None:
    from app.services import tenant_restores as tr

    suffix = uuid.uuid4().hex[:10]
    live, staging, previous = (f"cbi_swap_{kind}_{suffix}" for kind in ("live", "stage", "prev"))
    servers.created.extend([live, staging, previous])
    monkey = pytest.MonkeyPatch()
    monkey.setattr(tr, "_admin_url", servers.admin_url)
    try:
        async with servers.engine.connect() as connection:
            for name in (live, staging):
                await connection.execute(text(f"CREATE DATABASE {name} TEMPLATE template0"))
        for name, marker in ((live, "live-data"), (staging, "backup-data")):
            engine = _create_async_engine(servers.admin_url(name))
            async with engine.begin() as connection:
                await connection.execute(text("CREATE TABLE marker (value text)"))
                await connection.execute(text("INSERT INTO marker VALUES (:v)"), {"v": marker})
            await engine.dispose()

        async def value(database: str) -> str:
            engine = _create_async_engine(servers.admin_url(database))
            try:
                async with engine.connect() as connection:
                    return str(await connection.scalar(text("SELECT value FROM marker")))
            finally:
                await engine.dispose()

        await tr._swap(live, staging, previous)
        assert await value(live) == "backup-data"
        assert await value(previous) == "live-data"

        await tr._undo_swap(live, staging, previous)
        assert await value(live) == "live-data"
        # The staged copy is usable again, so the apply can be retried.
        assert await value(staging) == "backup-data"
        await tr._swap(live, staging, f"{previous}2")
        servers.created.append(f"{previous}2")
        assert await value(live) == "backup-data"
    finally:
        monkey.undo()
