"""Static checks on 0093_meetings: grants, row level security, reversibility, chain."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

VERSIONS = Path(__file__).resolve().parents[1] / "apps/api/alembic/versions"


def _load():
    spec = importlib.util.spec_from_file_location("m0093", VERSIONS / "0093_meetings.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(direction: str, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    module = _load()
    statements: list[str] = []
    monkeypatch.setattr(module.op, "execute", statements.append)
    getattr(module, direction)()
    return statements


def test_chain_continues_from_the_previous_head() -> None:
    module = _load()
    assert module.revision == "0093_meetings"
    assert module.down_revision == "0092_contacts_import_no_pause"


def test_every_new_table_is_granted_and_row_level_secured(monkeypatch) -> None:
    sql = _run("upgrade", monkeypatch)
    created = [m.group(1) for s in sql if (m := re.match(r"CREATE TABLE (\w+)", s))]
    assert len(created) == 9 and "meeting_pairing_codes" in created
    for table in created:
        assert f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO cbi_app" in sql
        assert f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY" in sql
        assert f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY" in sql
        assert any(f"CREATE POLICY {table}_tenant_isolation ON {table}" in s for s in sql)


def test_statements_are_single_commands_without_trailing_semicolons(monkeypatch) -> None:
    for direction in ("upgrade", "downgrade"):
        assert all(";" not in s for s in _run(direction, monkeypatch))


def test_downgrade_undoes_every_upgrade_change(monkeypatch) -> None:
    up, down = _run("upgrade", monkeypatch), _run("downgrade", monkeypatch)
    for table in [m.group(1) for s in up if (m := re.match(r"CREATE TABLE (\w+)", s))]:
        assert f"DROP TABLE {table}" in down
    for column in (
        "ALTER TABLE ledger_entries DROP COLUMN meeting_id",
        "ALTER TABLE credit_reservations DROP COLUMN meeting_id",
        "ALTER TABLE api_keys DROP COLUMN user_id",
        "ALTER TABLE api_keys DROP COLUMN kind",
    ):
        assert column in down
    assert "ALTER TABLE credit_reservations ALTER COLUMN call_id SET NOT NULL" in down


def test_pairing_codes_stay_in_the_control_database() -> None:
    from app.services.tenant_provisioning import _CONTROL_ONLY

    assert "meeting_pairing_codes" in _CONTROL_ONLY
    assert "meetings" not in _CONTROL_ONLY
