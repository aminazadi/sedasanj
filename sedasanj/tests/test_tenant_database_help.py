"""Every tenant database error code has a help article, and every alert reads a real metric."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType

import pytest

from app.services import tenant_db_metrics
from app.services.help_content import sanitize_help_html
from app.services.tenant_backups import BACKUP_ERRORS
from app.services.tenant_provisioning import MIGRATION_ERRORS
from app.services.tenant_restores import RESTORE_ERRORS

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "apps/api/alembic/versions/0141_tenant_database_help.py"
ALERTS = ROOT / "deploy/prometheus/alerts.yml"


@pytest.fixture(scope="module")
def migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("tenant_database_help", MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_code_has_exactly_one_help_row(migration: ModuleType) -> None:
    codes = [row[0] for row in migration.ERRORS]
    assert len(codes) == len(set(codes))
    assert set(codes) == set(MIGRATION_ERRORS) | set(BACKUP_ERRORS) | set(RESTORE_ERRORS)
    assert all(re.fullmatch(r"[A-Za-z0-9_.-]{2,40}", code) for code in codes)


def test_articles_name_the_code_an_action_and_survive_the_sanitizer(migration: ModuleType) -> None:
    slugs = [migration._slug(row[0]) for row in migration.ERRORS]
    assert len(slugs) == len(set(slugs))
    for code, _title, severity, cause, steps, quick, verify, prevent in migration.ERRORS:
        assert severity in {"info", "warning", "error", "critical"}
        assert steps and quick and verify and prevent
        body = migration.error_body(code, cause, steps, verify, prevent)
        assert code in body
        cleaned, _plain = sanitize_help_html(body)
        assert cleaned.count("<li>") == len(steps)
        assert re.search(r"[؀-ۿ]", cleaned)


def test_help_quick_action_matches_the_admin_message_action(migration: ModuleType) -> None:
    catalogs = {**MIGRATION_ERRORS, **BACKUP_ERRORS, **RESTORE_ERRORS}
    for row in migration.ERRORS:
        assert catalogs[row[0]][0], row[0]
        assert row[5], row[0]


def test_alerts_only_use_registered_tenant_metrics() -> None:
    registered = {
        "cbi_tenant_migrations",
        "cbi_tenant_database_registry",
        "cbi_tenant_restores",
        "cbi_tenant_migration_failures_total",
        "cbi_tenant_backup_failures_total",
        "cbi_tenant_restore_failures_total",
        "cbi_tenant_restores_applied_total",
        "cbi_tenant_backups_overdue",
        "cbi_tenant_backup_attempts_total",
    }
    used = set(re.findall(r"\bcbi_tenant_[a-z_]+", ALERTS.read_text()))
    assert used <= registered, used - registered
    # The counters and gauges the alerts rely on really exist in the metrics module.
    for name in (
        "migration_failures",
        "backup_failures",
        "restore_failures",
        "restores_applied",
        "migrations",
        "registry",
        "restores",
    ):
        assert hasattr(tenant_db_metrics, name)


def test_failure_counters_are_labeled_only_by_code() -> None:
    tenant_db_metrics.migration_failures.labels(code="TENANT_DB_UNKNOWN").inc()
    assert tenant_db_metrics.migration_failures._labelnames == ("code",)
    assert tenant_db_metrics.backup_failures._labelnames == ("code",)
    assert tenant_db_metrics.restore_failures._labelnames == ("code",)


def test_status_label_sets_cover_every_status_the_tables_allow() -> None:
    assert {"staged", "applying", "failed"} <= set(tenant_db_metrics.RESTORE_STATUSES)
    assert {"failed", "retryable"} <= set(tenant_db_metrics.MIGRATION_STATUSES)
    assert {"ready", "maintenance", "failed"} <= set(tenant_db_metrics.REGISTRY_STATUSES)
