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
