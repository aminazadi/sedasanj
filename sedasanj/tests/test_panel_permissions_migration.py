"""Panel permissions preserve role defaults when upgrading existing accounts."""

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy.dialects import postgresql


def test_panel_permissions_upgrade_and_downgrade(monkeypatch: pytest.MonkeyPatch) -> None:
    path = Path(__file__).parents[1] / "apps/api/alembic/versions/0112_user_panel_permissions.py"
    spec = importlib.util.spec_from_file_location("panel_permissions_migration", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    added = []
    removed = []
    monkeypatch.setattr(migration.op, "add_column", lambda *args: added.append(args))
    monkeypatch.setattr(migration.op, "drop_column", lambda *args: removed.append(args))

    migration.upgrade()

    assert len(added) == 1
    table, column = added[0]
    assert table == "users"
    assert column.name == "panel_permissions"
    assert isinstance(column.type, postgresql.JSONB)
    assert column.nullable
    assert column.server_default is None
    assert column.default is None

    migration.downgrade()

    assert removed == [("users", "panel_permissions")]
