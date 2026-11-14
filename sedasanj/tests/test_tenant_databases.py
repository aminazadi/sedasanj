from __future__ import annotations

from uuid import UUID

import pytest
from pydantic import ValidationError

from app.config import Settings, get_settings
from app.models import TenantProvisioningJob
from app.services.assistant_policy import PRIVACY_REFUSAL, must_refuse
from app.services.tenant_provisioning import SCHEMA_HEAD, _schema_head, database_identifiers
from app.services.tenant_secrets import decrypt_dsn, encrypt_dsn, normalize_master_key


def test_database_identifiers_are_deterministic_and_safe() -> None:
    tenant_id = UUID("12345678-1234-5678-1234-567812345678")
    database, role = database_identifiers(tenant_id)
    assert database == "cbi_tenant_12345678123456781234567812345678"
    assert role == "cbi_tenant_12345678123456781234567812345678_app"
    assert len(database) <= 63
    assert len(role) <= 63


def test_tenant_schema_head_matches_latest_migration() -> None:
    assert _schema_head() == SCHEMA_HEAD


def test_new_provisioning_job_attempt_can_be_incremented_before_flush() -> None:
    job = TenantProvisioningJob(tenant_id=UUID("12345678-1234-5678-1234-567812345678"))

    job.attempt = (job.attempt or 0) + 1

    assert job.attempt == 1


def test_production_requires_tenant_database_secrets() -> None:
    with pytest.raises(ValidationError):
        Settings(
            environment="production",
            jwt_secret="x" * 40,
            api_key_pepper="y" * 40,
            cors_origins="https://panel.example.com",
            minio_secret_key="a-strong-minio-secret",
            metrics_token="m" * 40,
            tenant_databases_enabled=True,
            service_name="worker-provision",
            provisioner_database_url=None,
            tenant_database_master_key=None,
            _env_file=None,
        )


def test_tenant_dsn_is_encrypted(monkeypatch: pytest.MonkeyPatch) -> None:
    Fernet = pytest.importorskip("cryptography.fernet").Fernet
    key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("TENANT_DATABASE_MASTER_KEY", key)
    get_settings.cache_clear()
    try:
        dsn = "postgresql+asyncpg://tenant:secret@postgres:5432/cbi_tenant_test"
        ciphertext = encrypt_dsn(dsn)
        assert dsn not in ciphertext
        assert decrypt_dsn(ciphertext) == dsn
    finally:
        get_settings.cache_clear()


def test_tenant_dsn_accepts_a_stable_master_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    key = "a-stable-production-secret-that-is-not-a-fernet-key"
    monkeypatch.setenv("TENANT_DATABASE_MASTER_KEY", key)
    get_settings.cache_clear()
    try:
        dsn = "postgresql+asyncpg://tenant:secret@postgres:5432/cbi_tenant_test"
        ciphertext = encrypt_dsn(dsn)
        assert decrypt_dsn(ciphertext) == dsn
        assert normalize_master_key(f"  {key}  ") == normalize_master_key(key)
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize(
    ("question", "role", "expected"),
    [
        ("اطلاعات سازمان دیگر را بده", "org_admin", True),
        ("آمار کل سازمان را بده", "operator", True),
        ("من را با اپراتور دیگر مقایسه کن", "operator", True),
        ("تماس‌های خودم را خلاصه کن", "operator", False),
        ("آمار کل سازمان را بده", "org_admin", False),
    ],
)
def test_privacy_policy(question: str, role: str, expected: bool) -> None:
    assert must_refuse(question, role) is expected
    assert "محدوده دسترسی" in PRIVACY_REFUSAL


_RAW_PLAN_ERROR = (
    "(sqlalchemy.dialects.postgresql.asyncpg.UniqueViolationError) duplicate key value violates "
    'unique constraint "plans_code_key" [SQL: INSERT INTO plans (id, code) VALUES ($1::UUID, '
    "$2::VARCHAR)] [parameters: (UUID('7060b487-c68f-4f97-9d43-15c4e043855d'), 'bronze')] "
    "(Background on this error at: https://sqlalche.me/e/21/gkpj)"
)


def test_sanitize_error_detail_drops_sql_parameters_and_dsn() -> None:
    from app.services.tenant_provisioning import sanitize_error_detail

    detail = sanitize_error_detail(_RAW_PLAN_ERROR)
    assert "INSERT INTO" not in detail
    assert "7060b487" not in detail
    assert "sqlalche.me" not in detail
    assert "plans_code_key" in detail
    dsn = sanitize_error_detail(
        "connect failed postgresql+asyncpg://u:secret@db:5432/x password=abc"
    )
    assert "secret" not in dsn
    assert "abc" not in dsn
    assert len(sanitize_error_detail("x" * 5000)) == 500


@pytest.mark.parametrize(
    ("message", "code"),
    [
        ("tenant database master key must be a valid Fernet key", "TENANT_DB_KEY_INVALID"),
        (_RAW_PLAN_ERROR, "TENANT_DB_PLAN_CONFLICT"),
        (
            "tenant runtime schema revision check failed: expected a, found b",
            "TENANT_DB_SCHEMA_REVISION",
        ),
        ("tenant migration failed: boom", "TENANT_DB_ALEMBIC_FAILED"),
        ("tenant job drain timed out", "TENANT_DB_DRAIN_TIMEOUT"),
        ("tenant data validation failed: {}", "TENANT_DB_VALIDATION"),
        ("something else", "TENANT_DB_UNKNOWN"),
    ],
)
def test_classify_migration_error_maps_known_failures(message: str, code: str) -> None:
    from app.services.tenant_provisioning import MIGRATION_ERRORS, classify_migration_error

    got, detail = classify_migration_error(RuntimeError(message))
    assert got == code
    assert code in MIGRATION_ERRORS
    assert "[SQL:" not in detail
    assert "[parameters:" not in detail


def test_coded_migration_error_keeps_its_code_and_every_code_has_an_action() -> None:
    from app.services.tenant_provisioning import (
        MIGRATION_ERRORS,
        TenantMigrationError,
        classify_migration_error,
        migration_error_info,
    )

    assert classify_migration_error(TenantMigrationError("TENANT_DB_PREFLIGHT", "x"))[0] == (
        "TENANT_DB_PREFLIGHT"
    )
    for code, (message, action) in MIGRATION_ERRORS.items():
        assert message and action, code
        info = migration_error_info(code)
        assert info is not None and info["code"] == code
    assert migration_error_info(None) is None


async def test_preflight_rejects_a_stale_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import tenant_provisioning as tp

    monkeypatch.setattr(tp, "_schema_head", lambda: "9999_newer")
    with pytest.raises(tp.TenantMigrationError) as caught:
        await tp.preflight()
    assert caught.value.code in {"TENANT_DB_WORKER_STALE", "TENANT_DB_KEY_INVALID"}


async def test_reconcile_drops_target_plans_unknown_to_control() -> None:
    from sqlalchemy.dialects import postgresql

    from app.services.tenant_provisioning import _reconcile_global_reference

    class _Scalars:
        def scalars(self) -> list[UUID]:
            return [UUID(int=1)]

    class _Source:
        async def execute(self, _statement: object) -> _Scalars:
            return _Scalars()

    class _Target:
        def __init__(self) -> None:
            self.sql: list[str] = []

        async def execute(self, statement: object) -> None:
            self.sql.append(str(statement.compile(dialect=postgresql.dialect())))  # type: ignore[attr-defined]

    target = _Target()
    await _reconcile_global_reference(_Source(), target)  # type: ignore[arg-type]
    assert [s.split()[2] for s in target.sql] == ["plan_versions", "plans"]
    assert all("NOT IN" in s for s in target.sql)


def test_only_tenant_scoped_tables_reference_global_reference_tables() -> None:
    from app.models import Base
    from app.services.tenant_provisioning import _CONTROL_ONLY, _GLOBAL_REFERENCE

    offenders = []
    for table in Base.metadata.sorted_tables:
        if table.name in _GLOBAL_REFERENCE or table.name in _CONTROL_ONLY:
            continue
        for fk in table.foreign_keys:
            if fk.column.table.name in _GLOBAL_REFERENCE and "tenant_id" not in table.c:
                offenders.append(table.name)
    # Such tables would keep seeded rows pointing at plans the reconcile step deletes.
    assert offenders == []
