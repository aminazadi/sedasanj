from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

INSECURE_DEFAULTS = frozenset({"change-me-change-me-change-me-32"})


def normalize_api_key(value: str | None) -> str:
    """Strip whitespace, wrapping quotes, and an accidental Bearer prefix."""
    if value is None:
        return ""
    secret = value.strip()
    if secret.lower().startswith("bearer "):
        secret = secret[7:].strip()
    if len(secret) >= 2 and secret[0] == secret[-1] and secret[0] in {'"', "'"}:
        secret = secret[1:-1].strip()
    return secret


class Settings(BaseSettings):
    """Runtime configuration, §7.4. Everything is env driven; nothing secret has a default."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://cbi:cbi@127.0.0.1:5432/cbi"
    provisioner_database_url: str | None = None
    tenant_database_master_key: str | None = None
    tenant_databases_enabled: bool = False
    tenant_database_auto_migrate: bool = False
    tenant_database_pool_size: int = Field(default=3, ge=1, le=20)
    tenant_database_max_pools: int = Field(default=20, ge=1, le=256)
    tenant_database_pool_idle_seconds: int = Field(default=900, ge=60, le=86400)
    tenant_migration_batch_size: int = Field(default=500, ge=10, le=5000)
    tenant_migration_max_attempts: int = Field(default=5, ge=1, le=20)
    tenant_migration_drain_seconds: int = Field(default=1800, ge=30, le=7200)
    tenant_migration_rollback_days: int = Field(default=7, ge=1, le=90)
    tenant_backup_enabled: bool = True
    tenant_backup_interval_hours: int = Field(default=24, ge=1, le=168)
    tenant_backup_retention_days: int = Field(default=30, ge=1, le=3650)
    redis_url: str = "redis://127.0.0.1:6379/0"

    environment: Literal["development", "production"] = "development"

    minio_endpoint: str = "http://127.0.0.1:9000"
    minio_public_endpoint: str | None = None
    minio_access_key: str = "cbi"
    minio_secret_key: str = "cbi-secret"
    minio_bucket_audio: str = "audio"
    minio_region: str = "us-east-1"

    jwt_secret: str = "change-me-change-me-change-me-32"
    access_token_ttl_minutes: int = 480
    refresh_token_ttl_days: int = 14
    api_key_pepper: str = "change-me-change-me-change-me-32"

    shenava_model_path: str = "/models/shenava-koochik-int8.bin"
    asr_engine: Literal["shenava", "whisper", "voicesanj", "fixture"] = "shenava"
    asr_model_name: str = "shenava-koochik"
    asr_model_version: str = "int8-v1"
    whisper_model: str = "whisper-1"
    whisper_base_url: str | None = None
    asr_language: str = "fa"
    # Runtime carriers populated from admin-managed platform settings.
    asr_provider_base_url: str | None = None
    asr_provider_api_key: str | None = None
    aiservice_asr_path: str = "/v1/audio/transcriptions"
    aiservice_analysis_path: str = "/v1/chat/tasks"
    aiservice_chat_path: str = "/v1/chat/tasks"
    aiservice_decision_path: str = "/v1/decisions"
    aiservice_embedding_path: str = "/v1/ninerouter/embeddings"

    # Optional, admin-managed audio preparation performed before ASR.  The
    # remote provider receives the resulting PCM WAV through its documented
    # transcription contract; no undocumented denoiser fields are sent.
    audio_preprocessing_enabled: bool = False
    audio_denoiser_model: Literal[
        "none", "speech-afftdn-balanced", "speech-afftdn-strong"
    ] = "speech-afftdn-balanced"
    audio_enhancement_model: Literal[
        "none", "speech-clarity-balanced", "speech-clarity-strong"
    ] = "speech-clarity-balanced"

    voice_sentiment_enabled: bool = False
    voice_sentiment_model: str = "iic/emotion2vec_plus_base"
    voice_sentiment_model_revision: str = "b318240bfe67db81a8c572ecb37ce9c3759b81c9"
    voice_sentiment_hub: Literal["hf", "huggingface", "ms", "modelscope"] = "hf"
    voice_sentiment_device: Literal["cpu"] = "cpu"
    voice_sentiment_cpu_threads: int = Field(default=2, ge=1, le=32)
    voice_sentiment_window_seconds: float = Field(default=8.0, ge=2.0, le=30.0)
    voice_sentiment_min_seconds: float = Field(default=1.0, ge=0.25, le=5.0)
    voice_sentiment_max_windows: int = Field(default=720, ge=10, le=5000)
    voice_sentiment_timeout_seconds: float = Field(default=900.0, ge=30.0, le=3600.0)
    max_concurrent_emotion_jobs: int = Field(default=1, ge=1, le=8)

    voicesanj_base_url: str = "https://aiservice.voicesanj.ir"
    # Runtime carrier only — set from admin Settings via resolve_provider_settings.
    voicesanj_api_key: str | None = None
    voicesanj_asr_model: str = "buzzasr-persian"
    voicesanj_llm_model: str = "dorna-8b-q4_k_m"
    voicesanj_text_correction_style: Literal["formal", "semi_formal", "action"] = "formal"
    voicesanj_correction_timeout_seconds: float = 120.0
    voicesanj_poll_interval_seconds: float = 2.0
    voicesanj_poll_timeout_seconds: float = 1800.0
    decision_api_key: str | None = None
    decision_model: str = "gliner2_5_multi_decide"
    decision_fallback_model: str = "laya_multilingual"
    decision_confidence_threshold: float = 0.72
    embedding_base_url: str | None = None
    embedding_api_key: str | None = None
    embedding_model: str = ""

    llama_server_urls: str = "http://llm1:8081,http://llm2:8081"
    llm_model: str = "dorna-llama3-8b-instruct-q4_k_m"
    llm_client: Literal["llama", "voicesanj", "fixture"] = "llama"
    prompt_version: str = "extract-fa-v3"
    llm_timeout_seconds: float = 300.0
    # Supported by VoiceSanj's documented ChatCompletionRequest (1..4096).
    llm_max_tokens: int = Field(default=1200, ge=256, le=4096)
    # Must stay below worker-llm's ARQ timeout so timeout failures pass through
    # the normal retry/failure bookkeeping instead of leaving a running row.
    analysis_timeout_seconds: float = Field(default=1500.0, ge=60.0, le=1700.0)
    max_concurrent_asr_jobs: int = Field(default=10, ge=1, le=256)
    max_concurrent_llm_submissions: int = Field(default=16, ge=1, le=256)
    analysis_concurrency: int = Field(default=1, ge=1, le=3)
    llm_poll_interval_seconds: float = Field(default=2.0, ge=0.25, le=60.0)
    outbox_dispatch_interval_seconds: float = Field(default=1.0, ge=0.25, le=30.0)
    # Runtime carrier only — set from admin Settings via resolve_provider_settings.
    openai_api_key: str | None = None

    smtp_url: str | None = None
    notify_from_email: str = "noreply@example.com"
    balance_low_threshold_seconds: int = 600

    smsir_api_key: str | None = None
    smsir_verify_template_id: int | None = None
    smsir_base_url: str = "https://api.sms.ir/v1"
    zarinpal_merchant_id: str | None = None
    zarinpal_sandbox: bool = False
    public_app_url: str = "http://localhost:5173"
    sales_notification_email: str | None = None
    support_email: str | None = None

    public_base_url: str = "http://localhost:8000"
    cors_origins: str = ""
    worker_metrics_port: int = 9100
    metrics_token: str | None = None
    audio_presign_ttl_seconds: int = 60
    storage_backend: Literal["s3", "memory"] = "s3"
    queue_backend: Literal["redis", "memory"] = "redis"

    rate_limit_uploads_per_minute: int = 30
    rate_limit_reads_per_minute: int = 120

    max_upload_bytes: int = 200 * 1024 * 1024
    max_extracted_audio_bytes: int = 512 * 1024 * 1024
    max_archive_compression_ratio: int = Field(default=100, ge=1, le=1000)
    min_billable_seconds: int = 30
    duration_mismatch_tolerance: float = Field(default=0.2, ge=0.0, le=1.0)

    service_name: str = "api"
    log_level: str = "INFO"

    @field_validator(
        "voicesanj_api_key", "openai_api_key", "asr_provider_api_key", "decision_api_key", mode="before"
    )
    @classmethod
    def _normalize_provider_api_keys(cls, value: object) -> object:
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        normalized = normalize_api_key(value)
        return normalized or None

    @field_validator("smsir_verify_template_id", mode="before")
    @classmethod
    def _normalize_optional_integer(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @property
    def llama_urls(self) -> list[str]:
        return [u.strip().rstrip("/") for u in self.llama_server_urls.split(",") if u.strip()]

    @property
    def cors_origin_list(self) -> list[str]:
        return [
            origin.strip().rstrip("/") for origin in self.cors_origins.split(",") if origin.strip()
        ]

    @property
    def presign_endpoint(self) -> str:
        """Browsers cannot resolve the compose-internal MinIO host (§11)."""
        return self.minio_public_endpoint or self.minio_endpoint

    @model_validator(mode="after")
    def _reject_insecure_production(self) -> Self:
        if self.environment != "production":
            return self
        weak = [
            name
            for name, value in (
                ("JWT_SECRET", self.jwt_secret),
                ("API_KEY_PEPPER", self.api_key_pepper),
            )
            if value in INSECURE_DEFAULTS or len(value) < 32
        ]
        if weak:
            raise ValueError(f"{', '.join(weak)} must be set to a value of at least 32 characters")
        if self.minio_secret_key == "cbi-secret" or len(self.minio_secret_key) < 8:
            raise ValueError("MINIO_SECRET_KEY must be set to a strong value in production")
        if not self.metrics_token or len(self.metrics_token) < 32:
            raise ValueError("METRICS_TOKEN must be set to at least 32 characters in production")
        if not self.cors_origin_list:
            raise ValueError("CORS_ORIGINS must list the panel origins in production")
        if self.tenant_databases_enabled:
            if self.service_name == "worker-provision" and not self.provisioner_database_url:
                raise ValueError("PROVISIONER_DATABASE_URL is required for tenant databases")
            if not self.tenant_database_master_key:
                raise ValueError("TENANT_DATABASE_MASTER_KEY is required for tenant databases")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
