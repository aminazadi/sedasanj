from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from app.config import Settings


def _prod_kwargs(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "environment": "production",
        "jwt_secret": "x" * 40,
        "api_key_pepper": "y" * 40,
        "cors_origins": "https://panel.example.com",
        "minio_secret_key": "a-strong-minio-secret",
        "metrics_token": "m" * 40,
        "platform_secrets_key": Fernet.generate_key().decode("ascii"),
    }
    base.update(overrides)
    return base


def test_settings_strips_quoted_provider_api_keys() -> None:
    settings = Settings(
        environment="development",
        voicesanj_api_key='"secret-from-env"',
        openai_api_key="Bearer other-secret",
    )
    assert settings.voicesanj_api_key == "secret-from-env"
    assert settings.openai_api_key == "other-secret"


def test_audio_preprocessing_is_safe_by_default() -> None:
    settings = Settings(environment="development")
    assert settings.audio_preprocessing_enabled is False
    assert settings.audio_denoiser_model == "speech-afftdn-balanced"
    assert settings.audio_enhancement_model == "speech-clarity-balanced"
    assert settings.audio_target_loudness_lufs == -20.0
    assert settings.audio_max_gain_db == 30.0


def test_voicesanj_default_uses_https() -> None:
    settings = Settings(environment="development", _env_file=None)
    assert settings.voicesanj_base_url == "https://aiservice.voicesanj.ir"
    assert settings.aiservice_decision_path == "/v1/decisions"
    assert settings.aiservice_embedding_path == "/v1/embeddings"


@pytest.mark.parametrize("value", ["", "   "])
def test_blank_smsir_verify_template_id_is_unset(value: str) -> None:
    settings = Settings(environment="development", smsir_verify_template_id=value)
    assert settings.smsir_verify_template_id is None


def test_smsir_verify_template_id_accepts_numeric_strings() -> None:
    settings = Settings(environment="development", smsir_verify_template_id="123456")
    assert settings.smsir_verify_template_id == 123456


@pytest.mark.parametrize("value", ["", "   ", "\t\n"])
@pytest.mark.parametrize("production", [False, True])
def test_blank_ml_publisher_tenant_env_is_unset(
    monkeypatch: pytest.MonkeyPatch, value: str, production: bool
) -> None:
    monkeypatch.setenv("ML_PUBLISHER_TENANT_ID", value)
    kwargs = _prod_kwargs() if production else {"environment": "development"}
    assert Settings(_env_file=None, **kwargs).ml_publisher_tenant_id is None


def test_blank_ml_publisher_tenant_dotenv_is_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ML_PUBLISHER_TENANT_ID", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("ML_PUBLISHER_TENANT_ID=\n", encoding="utf-8")
    assert Settings(environment="development", _env_file=env_file).ml_publisher_tenant_id is None


@pytest.mark.parametrize("as_string", [False, True])
def test_ml_publisher_tenant_accepts_uuid(as_string: bool) -> None:
    tenant_id = UUID("3c7837a1-1743-4ae4-a9df-22688d41f930")
    settings = Settings(
        environment="development",
        _env_file=None,
        ml_publisher_tenant_id=str(tenant_id) if as_string else tenant_id,
    )
    assert settings.ml_publisher_tenant_id == tenant_id


@pytest.mark.parametrize("value", ["not-a-uuid", "0", "null"])
def test_invalid_ml_publisher_tenant_env_is_rejected(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("ML_PUBLISHER_TENANT_ID", value)
    with pytest.raises(ValidationError, match="ml_publisher_tenant_id"):
        Settings(environment="development", _env_file=None)


def test_production_accepts_strong_secrets() -> None:
    Settings(**_prod_kwargs())


def test_production_rejects_default_minio_secret() -> None:
    with pytest.raises(ValidationError):
        Settings(**_prod_kwargs(minio_secret_key="cbi-secret"))


def test_production_rejects_short_minio_secret() -> None:
    with pytest.raises(ValidationError):
        Settings(**_prod_kwargs(minio_secret_key="short"))


def test_production_rejects_default_jwt_secret() -> None:
    with pytest.raises(ValidationError):
        Settings(**_prod_kwargs(jwt_secret="change-me-change-me-change-me-32"))


def test_production_requires_cors_origins() -> None:
    with pytest.raises(ValidationError):
        Settings(**_prod_kwargs(cors_origins=""))


@pytest.mark.parametrize("metrics_token", [None, "short"])
def test_production_requires_strong_metrics_token(metrics_token: str | None) -> None:
    with pytest.raises(ValidationError):
        Settings(**_prod_kwargs(metrics_token=metrics_token))


def test_production_requires_a_valid_platform_secrets_key() -> None:
    with pytest.raises(ValidationError, match="PLATFORM_SECRETS_KEY"):
        Settings(**_prod_kwargs(platform_secrets_key=None))
    with pytest.raises(ValidationError, match="PLATFORM_SECRETS_KEY"):
        Settings(**_prod_kwargs(platform_secrets_key="not-a-fernet-key"))


def test_production_rejects_jwt_secret_equal_to_pepper() -> None:
    with pytest.raises(ValidationError, match="different"):
        Settings(**_prod_kwargs(jwt_secret="z" * 40, api_key_pepper="z" * 40))


def test_dev_otp_needs_explicit_development_flag() -> None:
    assert Settings(environment="development", allow_insecure_dev=True).dev_otp_visible
    assert not Settings(environment="development", allow_insecure_dev=False).dev_otp_visible
    assert not Settings(**_prod_kwargs(allow_insecure_dev=True)).dev_otp_visible
