from __future__ import annotations

from uuid import UUID

import pytest
from pydantic import ValidationError

from app.config import Settings, get_settings
from app.models import TenantProvisioningJob
from app.services.assistant_policy import PRIVACY_REFUSAL, must_refuse
from app.services.tenant_provisioning import SCHEMA_HEAD, _schema_head, database_identifiers
from app.services.tenant_secrets import decrypt_dsn, encrypt_dsn


def test_database_identifiers_are_deterministic_and_safe() -> None:
    tenant_id = UUID("12345678-1234-5678-1234-567812345678")
    database, role = database_identifiers(tenant_id)
    assert database == "cbi_tenant_12345678123456781234567812345678"
    assert role == "cbi_tenant_12345678123456781234567812345678_app"
    assert len(database) <= 63
    assert len(role) <= 63


def test_tenant_schema_head_matches_latest_migration() -> None:
    assert SCHEMA_HEAD == "0039_operator_score_needs_review"
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
