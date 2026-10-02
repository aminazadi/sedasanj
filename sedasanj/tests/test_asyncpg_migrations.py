from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

MIGRATION_DIR = (
    Path(__file__).resolve().parents[1] / "apps" / "api" / "alembic" / "versions"
)
MIGRATIONS = (
    "0020_tenant_database_control_plane.py",
    "0021_identity_projection_outbox.py",
    "0022_tenant_backups.py",
    "0023_projection_state.py",
    "0024_hybrid_knowledge.py",
    "0025_sales_kpi_center.py",
    "0026_balance_cache_integrity.py",
)


def _load_migration(filename: str) -> ModuleType:
    path = MIGRATION_DIR / filename
    spec = importlib.util.spec_from_file_location(f"test_{path.stem}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("filename", MIGRATIONS)
def test_asyncpg_migrations_execute_one_command_at_a_time(
    filename: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    migration = _load_migration(filename)
    statements: list[str] = []
    monkeypatch.setattr(migration.op, "execute", statements.append)

    migration.upgrade()

    assert statements
    assert all(";" not in statement for statement in statements)


class _ScalarResult:
    def __init__(self, value: object) -> None:
        self.value = value

    def scalar_one_or_none(self) -> object:
        return self.value


class _AgeBind:
    def __init__(self, graph_exists: bool) -> None:
        self.graph_exists = graph_exists
        self.statements: list[str] = []

    def execute(self, statement: object) -> _ScalarResult:
        sql = str(statement)
        self.statements.append(sql)
        if "FROM ag_catalog.ag_graph" in sql:
            return _ScalarResult(1 if self.graph_exists else None)
        return _ScalarResult(None)


@pytest.mark.parametrize("graph_exists", [False, True])
def test_apache_age_migration_is_idempotent(
    graph_exists: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    migration = _load_migration("0031_apache_age_graph.py")
    bind = _AgeBind(graph_exists)
    monkeypatch.setattr(migration.op, "get_bind", lambda: bind)

    migration.upgrade()

    assert bind.statements[0] == "CREATE EXTENSION IF NOT EXISTS age"
    assert any("GRANT USAGE ON SCHEMA ag_catalog" in sql for sql in bind.statements)
    assert any("GRANT USAGE, CREATE ON SCHEMA tenant_graph" in sql for sql in bind.statements)
    create_graph = [sql for sql in bind.statements if "create_graph" in sql]
    assert bool(create_graph) is not graph_exists


@pytest.mark.parametrize("graph_exists", [False, True])
def test_apache_age_repair_migration_is_idempotent(
    graph_exists: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    migration = _load_migration("0032_repair_apache_age_graph.py")
    bind = _AgeBind(graph_exists)
    monkeypatch.setattr(migration.op, "get_bind", lambda: bind)

    migration.upgrade()

    assert bind.statements[0] == "CREATE EXTENSION IF NOT EXISTS age"
    assert any("GRANT USAGE ON SCHEMA ag_catalog" in sql for sql in bind.statements)
    assert any("GRANT USAGE, CREATE ON SCHEMA tenant_graph" in sql for sql in bind.statements)
    create_graph = [sql for sql in bind.statements if "create_graph" in sql]
    assert bool(create_graph) is not graph_exists
