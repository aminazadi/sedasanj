"""0097_jalase_negar_releases: grants, constraints, reversibility and chain."""

from __future__ import annotations

import importlib.util
import os
import re
from pathlib import Path

import pytest

VERSIONS = Path(__file__).resolve().parents[1] / "apps/api/alembic/versions"


def _load():
    spec = importlib.util.spec_from_file_location(
        "m0097", VERSIONS / "0097_jalase_negar_releases.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(direction: str, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    module = _load()
    statements: list[str] = []
    monkeypatch.setattr(module.op, "execute", statements.append)
    monkeypatch.setattr(module.op, "drop_table", lambda name: statements.append(f"DROP {name}"))
    getattr(module, direction)()
    return statements


def test_chain_continues_from_the_previous_head() -> None:
    module = _load()
    assert module.revision == "0097_jalase_negar_releases"
    assert module.down_revision == "0096_meeting_text_help_content"


def test_table_is_granted_and_unique_per_version(monkeypatch: pytest.MonkeyPatch) -> None:
    sql = _run("upgrade", monkeypatch)
    assert "GRANT SELECT, INSERT, UPDATE, DELETE ON jalase_negar_releases TO cbi_app" in sql
    create = next(s for s in sql if s.startswith("CREATE TABLE jalase_negar_releases"))
    assert "UNIQUE (version_code)" in create and "UNIQUE (version_name)" in create
    assert "CHECK (status IN ('draft','published','revoked'))" in create.replace("\n", "")


def test_statements_are_single_commands_without_trailing_semicolons(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for direction in ("upgrade", "downgrade"):
        assert all(not re.search(r";\s*$", s) for s in _run(direction, monkeypatch))


def test_downgrade_drops_the_table(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _run("downgrade", monkeypatch) == ["DROP jalase_negar_releases"]


def test_table_is_control_plane_only() -> None:
    from app.services.tenant_provisioning import _CONTROL_ONLY

    assert "jalase_negar_releases" in _CONTROL_ONLY


def test_model_matches_the_migration_columns() -> None:
    from app.models import JalaseNegarRelease

    module = _load()
    sql = "\n".join(_collect(module))
    columns = {column.name for column in JalaseNegarRelease.__table__.columns}
    declared = set(re.findall(r"^\s{4}(\w+) [A-Z]", sql, re.M))
    assert columns <= declared


def _collect(module) -> list[str]:  # type: ignore[no-untyped-def]
    captured: list[str] = []
    original = module.op.execute
    module.op.execute = captured.append
    try:
        module.upgrade()
    finally:
        module.op.execute = original
    return captured


TEST_DSN = os.environ.get("JALASE_NEGAR_TEST_DSN")


@pytest.mark.skipif(not TEST_DSN, reason="disposable PostgreSQL DSN not supplied")
async def test_upgrade_and_downgrade_round_trip_on_postgres() -> None:
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    assert TEST_DSN and ("test" in TEST_DSN.rsplit("/", 1)[-1])
    module = _load()
    engine = create_async_engine(TEST_DSN)

    def run(connection, direction: str) -> None:  # type: ignore[no-untyped-def]
        with Operations.context(MigrationContext.configure(connection)):
            getattr(module, direction)()

    async with engine.begin() as connection:
        await connection.execute(text("DROP TABLE IF EXISTS jalase_negar_releases"))
        await connection.execute(
            text("CREATE TABLE IF NOT EXISTS staff_users (id UUID PRIMARY KEY)")
        )
        await connection.run_sync(run, "upgrade")
        columns = (
            (
                await connection.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'jalase_negar_releases'"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert {"version_code", "signing_cert_sha256", "abis", "status"} <= set(columns)
        await connection.execute(
            text(
                "INSERT INTO jalase_negar_releases (package_name, version_name, version_code, "
                "min_sdk, title, artifact_key, artifact_sha256, artifact_size, "
                "signing_cert_sha256, status) VALUES ('p','1.0.0',1,24,'t','k',:h,1,:h,'draft')"
            ),
            {"h": "a" * 64},
        )
        with pytest.raises(Exception, match="version_code_key"):
            async with connection.begin_nested():
                await connection.execute(
                    text(
                        "INSERT INTO jalase_negar_releases (package_name, version_name, "
                        "version_code, min_sdk, title, artifact_key, artifact_sha256, "
                        "artifact_size, signing_cert_sha256, status) VALUES "
                        "('p','1.0.1',1,24,'t','k2',:h,1,:h,'draft')"
                    ),
                    {"h": "a" * 64},
                )
        await connection.run_sync(run, "downgrade")
        left = (
            await connection.execute(text("SELECT to_regclass('jalase_negar_releases')"))
        ).scalar_one()
        assert left is None
        await connection.run_sync(run, "upgrade")
        await connection.run_sync(run, "downgrade")
    await engine.dispose()
