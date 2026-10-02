from __future__ import annotations

from typing import Any

import pytest
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
