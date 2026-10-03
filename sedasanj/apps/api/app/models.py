from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, CITEXT, INET, JSONB, REAL, TSVECTOR
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import UserDefinedType

TSTZ = DateTime(timezone=True)

CALL_STATUSES = (
    "received",
    "reserved",
    "stored",
    "transcribing",
    "transcribed",
    "correcting",
    "emotion_queued",
    "emotion_analyzing",
    "analyzing",
    "analyzed",
    "billed",
    "notified",
    "complete",
    "failed_retryable",
    "failed_terminal",
    "canceled",
)


class Base(DeclarativeBase):
    pass


class VectorType(UserDefinedType[Any]):
    cache_ok = True

    def get_col_spec(self, **kw: Any) -> str:
        return "vector"


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"))
    timezone: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'Asia/Tehran'")
    )
    locale: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'fa'"))
    price_per_minute_toman: Mapped[int] = mapped_column(Integer, nullable=False)
    monthly_minute_quota: Mapped[int | None] = mapped_column(Integer)
    max_concurrent_jobs: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("10")
    )
    audio_retention_days: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("30")
    )
    max_operators: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("5"))
    operator_ranking_visible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(TSTZ, server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','provisioning','active','maintenance_readonly',"
            "'migration_failed','suspended','deleted')",
            name="tenants_status_check",
        ),
        CheckConstraint("max_operators >= 0", name="tenants_max_operators_check"),
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    email: Mapped[str] = mapped_column(CITEXT, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    totp_secret: Mapped[str | None] = mapped_column(Text)
    totp_pending_secret: Mapped[str | None] = mapped_column(Text)
    mobile_number: Mapped[str | None] = mapped_column(Text)
    extension: Mapped[str | None] = mapped_column(Text)
    display_name: Mapped[str | None] = mapped_column(Text)
    profile_context: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TSTZ, server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("tenant_id", "email", name="users_tenant_email_key"),
        CheckConstraint("role IN ('org_admin','operator','viewer')", name="users_role_check"),
        Index(
            "users_tenant_extension_key",
            "tenant_id",
            "extension",
            unique=True,
            postgresql_where=text("extension IS NOT NULL AND btrim(extension) <> ''"),
        ),
        Index(
            "users_tenant_mobile_key",
            "tenant_id",
            "mobile_number",
            unique=True,
            postgresql_where=text("mobile_number IS NOT NULL AND btrim(mobile_number) <> ''"),
        ),
    )


class StaffUser(Base):
    __tablename__ = "staff_users"

    totp_secret: Mapped[str | None] = mapped_column(Text)
    totp_pending_secret: Mapped[str | None] = mapped_column(Text)

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    email: Mapped[str] = mapped_column(CITEXT, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    disabled_at: Mapped[datetime | None] = mapped_column(TSTZ)
    created_at: Mapped[datetime] = mapped_column(TSTZ, server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("role IN ('super_admin','support')", name="staff_users_role_check"),
    )


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(TSTZ, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(TSTZ)
    created_at: Mapped[datetime] = mapped_column(TSTZ, server_default=func.now(), nullable=False)


class StaffRefreshToken(Base):
    __tablename__ = "staff_refresh_tokens"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    staff_user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("staff_users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(TSTZ, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(TSTZ)
    created_at: Mapped[datetime] = mapped_column(TSTZ, server_default=func.now(), nullable=False)


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    key_hash: Mapped[str] = mapped_column(Text, nullable=False)
    key_prefix: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str | None] = mapped_column(Text)
    archive_format: Mapped[str] = mapped_column(Text, nullable=False, default="gzip")
    archive_password_hash: Mapped[str | None] = mapped_column(Text)
    last_used_at: Mapped[datetime | None] = mapped_column(TSTZ)
    revoked_at: Mapped[datetime | None] = mapped_column(TSTZ)
    created_at: Mapped[datetime] = mapped_column(TSTZ, server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "archive_format IN ('wav','gzip','zip')", name="api_keys_archive_format_check"
        ),
    )


class AudioObject(Base):
    __tablename__ = "audio_objects"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    bucket: Mapped[str] = mapped_column(Text, nullable=False)
    object_key: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(Text, nullable=False)
    bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sample_rate: Mapped[int] = mapped_column(Integer, nullable=False)
    channels: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(TSTZ)
    deleted_at: Mapped[datetime | None] = mapped_column(TSTZ)
    created_at: Mapped[datetime] = mapped_column(TSTZ, server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_audio_expiry", "expires_at", postgresql_where=text("expires_at IS NOT NULL")),
    )


class Call(Base):
    __tablename__ = "calls"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    audio_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("audio_objects.id")
    )
    asterisk_uniqueid: Mapped[str] = mapped_column(Text, nullable=False)
    caller_number: Mapped[str | None] = mapped_column(Text)
    dialed_number: Mapped[str | None] = mapped_column(Text)
    direction: Mapped[str | None] = mapped_column(Text)
    agent_extension: Mapped[str | None] = mapped_column(Text)
    campaign_id: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(Text)
    external_reference: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(TSTZ, nullable=False)
    ended_at: Mapped[datetime] = mapped_column(TSTZ, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    billed_seconds: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    error_code: Mapped[str | None] = mapped_column(Text)
    progress_pct: Mapped[int | None] = mapped_column(SmallInteger)
    progress_detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TSTZ, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TSTZ, server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("tenant_id", "asterisk_uniqueid", name="calls_tenant_uniqueid_key"),
        CheckConstraint(
            "progress_pct IS NULL OR (progress_pct >= 0 AND progress_pct <= 100)",
            name="calls_progress_pct_check",
        ),
        Index("idx_calls_tenant_started", "tenant_id", text("started_at DESC")),
        Index("idx_calls_tenant_status", "tenant_id", "status"),
        Index("idx_calls_tenant_campaign", "tenant_id", "campaign_id", "started_at"),
        Index("idx_calls_tenant_external_reference", "tenant_id", "external_reference"),
        Index(
            "idx_calls_caller_trgm",
            "caller_number",
            postgresql_using="gin",
            postgresql_ops={"caller_number": "gin_trgm_ops"},
        ),
    )


class CallOperatorAssignment(Base):
    __tablename__ = "call_operator_assignments"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    call_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("calls.id", ondelete="CASCADE"), nullable=False
    )
    operator_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    agent_extension: Mapped[str] = mapped_column(Text, nullable=False)
    assignment_source: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(REAL, nullable=False, server_default=text("1"))
    assigned_at: Mapped[datetime] = mapped_column(TSTZ, server_default=func.now(), nullable=False)
    superseded_at: Mapped[datetime | None] = mapped_column(TSTZ)

    __table_args__ = (
        Index(
            "idx_call_operator_assignment_active",
            "tenant_id",
            "operator_id",
            "call_id",
            unique=True,
            postgresql_where=text("superseded_at IS NULL"),
        ),
    )


class Utterance(Base):
    __tablename__ = "utterances"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    call_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("calls.id", ondelete="CASCADE"), nullable=False
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    channel: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    t_start_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    t_end_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float | None] = mapped_column(REAL)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB)

    __table_args__ = (
        CheckConstraint("channel IN (0,1)", name="utterances_channel_check"),
        Index("idx_utterances_call", "call_id", "t_start_ms"),
    )


class Transcript(Base):
    __tablename__ = "transcripts"

    call_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("calls.id", ondelete="CASCADE"), primary_key=True
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    full_text: Mapped[str] = mapped_column(Text, nullable=False)
    corrected_text: Mapped[str | None] = mapped_column(Text)
    corrected_at: Mapped[datetime | None] = mapped_column(TSTZ)
    active_revision_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("transcript_revisions.id", ondelete="SET NULL")
    )
    active_asr_revision_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("asr_transcript_revisions.id", ondelete="SET NULL")
    )
    search: Mapped[str] = mapped_column(
        TSVECTOR, Computed("to_tsvector('simple', full_text)", persisted=True)
    )
    asr_model: Mapped[str] = mapped_column(Text, nullable=False)
    asr_version: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TSTZ, server_default=func.now(), nullable=False)

    __table_args__ = (Index("idx_transcripts_search", "search", postgresql_using="gin"),)


class TranscriptRevision(Base):
    __tablename__ = "transcript_revisions"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    call_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("calls.id", ondelete="CASCADE"), nullable=False
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    source_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    asr_revision_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("asr_transcript_revisions.id", ondelete="SET NULL")
    )
    profile_version: Mapped[str] = mapped_column(Text, nullable=False)
    trigger: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    audio_models: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    text_models: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    corrected_text: Mapped[str | None] = mapped_column(Text)
    provider_task_id: Mapped[str | None] = mapped_column(Text)
    provider_model: Mapped[str | None] = mapped_column(Text)
    uncertain_items: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error_code: Mapped[str | None] = mapped_column(Text)
    error_detail: Mapped[str | None] = mapped_column(Text)
    queued_at: Mapped[datetime] = mapped_column(TSTZ, server_default=func.now(), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(TSTZ)
    provider_submitted_at: Mapped[datetime | None] = mapped_column(TSTZ)
    completed_at: Mapped[datetime | None] = mapped_column(TSTZ)
    activated_at: Mapped[datetime | None] = mapped_column(TSTZ)
    created_at: Mapped[datetime] = mapped_column(TSTZ, server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "trigger IN ('automatic','manual')", name="transcript_revisions_trigger_check"
        ),
        CheckConstraint(
            "mode IN ('text_only','audio_only','two_stage')",
            name="transcript_revisions_mode_check",
        ),
        CheckConstraint(
            "status IN ('queued','running','validating','succeeded','failed')",
            name="transcript_revisions_status_check",
        ),
        Index("idx_transcript_revisions_call", "call_id", text("created_at DESC")),
        Index("idx_transcript_revisions_pending", "status", "queued_at"),
    )


class TranscriptRevisionSegment(Base):
    __tablename__ = "transcript_revision_segments"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    revision_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("transcript_revisions.id", ondelete="CASCADE"),
        nullable=False,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    source_utterance_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("utterances.id", ondelete="SET NULL")
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    channel: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    t_start_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    t_end_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    corrected_text: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float | None] = mapped_column(REAL)
    uncertain: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB)

    __table_args__ = (
        CheckConstraint("channel IN (0,1)", name="transcript_revision_segments_channel_check"),
        UniqueConstraint(
            "revision_id", "position", name="transcript_revision_segments_revision_position_key"
        ),
        Index("idx_transcript_revision_segments_revision", "revision_id", "position"),
    )


class AsrTranscriptRevision(Base):
    __tablename__ = "asr_transcript_revisions"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    call_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("calls.id", ondelete="CASCADE"), nullable=False
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(Text, nullable=False)
    trigger: Mapped[str] = mapped_column(Text, nullable=False)
    full_text: Mapped[str | None] = mapped_column(Text)
    asr_model: Mapped[str | None] = mapped_column(Text)
    asr_version: Mapped[str | None] = mapped_column(Text)
    speaker_mode: Mapped[str | None] = mapped_column(Text)
    timestamp_source: Mapped[str | None] = mapped_column(Text)
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error_code: Mapped[str | None] = mapped_column(Text)
    error_detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TSTZ, server_default=func.now(), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(TSTZ)
    activated_at: Mapped[datetime | None] = mapped_column(TSTZ)

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','running','succeeded','failed')",
            name="asr_transcript_revisions_status_check",
        ),
        CheckConstraint(
            "trigger IN ('initial','manual')", name="asr_transcript_revisions_trigger_check"
        ),
        Index("idx_asr_transcript_revisions_call", "call_id", text("created_at DESC")),
    )


class AsrTranscriptRevisionSegment(Base):
    __tablename__ = "asr_transcript_revision_segments"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    revision_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("asr_transcript_revisions.id", ondelete="CASCADE"),
        nullable=False,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    channel: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    t_start_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    t_end_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float | None] = mapped_column(REAL)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB)

    __table_args__ = (
        CheckConstraint("channel IN (0,1)", name="asr_revision_segments_channel_check"),
        UniqueConstraint(
            "revision_id", "position", name="asr_revision_segments_revision_position_key"
        ),
        Index("idx_asr_revision_segments_revision", "revision_id", "position"),
    )


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    call_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("calls.id", ondelete="CASCADE"), nullable=False
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    llm_model: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_version: Mapped[str] = mapped_column(Text, nullable=False)
    system_prompt: Mapped[str | None] = mapped_column(Text)
    raw_output: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TSTZ, server_default=func.now(), nullable=False)

    __table_args__ = (Index("idx_analysis_runs_call", "call_id", text("created_at DESC")),)


class AnalysisStep(Base):
    __tablename__ = "analysis_steps"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    analysis_run_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    status: Mapped[str] = mapped_column(Text, nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    input_text: Mapped[str] = mapped_column(Text, nullable=False)
    input_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    provider_task_id: Mapped[str | None] = mapped_column(Text)
    result_text: Mapped[str | None] = mapped_column(Text)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    error_code: Mapped[str | None] = mapped_column(Text)
    error_detail: Mapped[str | None] = mapped_column(Text)
    queued_at: Mapped[datetime] = mapped_column(TSTZ, server_default=func.now(), nullable=False)
    submitted_at: Mapped[datetime | None] = mapped_column(TSTZ)
    completed_at: Mapped[datetime | None] = mapped_column(TSTZ)
    created_at: Mapped[datetime] = mapped_column(TSTZ, server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "kind IN ('map','reduce','extract','repair')",
            name="analysis_steps_kind_check",
        ),
        CheckConstraint(
            "status IN ('queued','submitted','polling','succeeded','failed')",
            name="analysis_steps_status_check",
        ),
        UniqueConstraint(
            "analysis_run_id", "kind", "ordinal", name="analysis_steps_run_kind_ordinal_key"
        ),
        Index("idx_analysis_steps_pending", "status", "queued_at"),
    )


class CallInsight(Base):
    __tablename__ = "call_insights"

    call_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("calls.id", ondelete="CASCADE"), primary_key=True
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    summary: Mapped[str | None] = mapped_column(Text)
    keywords: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    sentiment: Mapped[str | None] = mapped_column(Text)
    sentiment_score: Mapped[float | None] = mapped_column(REAL)
    sentiment_profile: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    intent: Mapped[str | None] = mapped_column(Text)
    topics: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    ner: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    action_items: Mapped[Any | None] = mapped_column(JSONB)

    __table_args__ = (
        CheckConstraint(
            "sentiment IN ('angry','sad','neutral','satisfied','happy')",
            name="call_insights_sentiment_check",
        ),
        Index("idx_insights_keywords", "keywords", postgresql_using="gin"),
        Index("idx_insights_ner", "ner", postgresql_using="gin"),
    )


class SalesInsight(Base):
    __tablename__ = "sales_insights"
    call_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("calls.id", ondelete="CASCADE"), primary_key=True
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    analysis_run_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("analysis_runs.id", ondelete="SET NULL")
    )
    taxonomy_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    funnel_stage: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'unknown'")
    )
    outcome: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'unknown'"))
    certainty: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'unknown'"))
    confidence: Mapped[float] = mapped_column(REAL, nullable=False, server_default=text("0"))
    product: Mapped[str | None] = mapped_column(Text)
    objections: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'")
    )
    win_loss_reason: Mapped[str | None] = mapped_column(Text)
    next_action: Mapped[str | None] = mapped_column(Text)
    next_action_due_at: Mapped[datetime | None] = mapped_column(TSTZ)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'")
    )
    created_at: Mapped[datetime] = mapped_column(TSTZ, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TSTZ, server_default=func.now(), nullable=False)
    __table_args__ = (
        CheckConstraint(
            "funnel_stage IN ('all_calls','effective','qualified','interested',"
            "'follow_up','proposal','won','lost','unknown')",
            name="sales_insights_funnel_stage_check",
        ),
        CheckConstraint(
            "outcome IN ('won','lost','follow_up','interested','not_qualified','unknown')",
            name="sales_insights_outcome_check",
        ),
        CheckConstraint(
            "certainty IN ('explicit','probable','unknown')", name="sales_insights_certainty_check"
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="sales_insights_confidence_check"
        ),
        Index("idx_sales_insights_tenant_outcome", "tenant_id", "outcome", "certainty"),
    )


class Team(Base):
    __tablename__ = "teams"
    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(TSTZ, server_default=func.now(), nullable=False)
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="teams_tenant_name_key"),)


class TeamMembership(Base):
    __tablename__ = "team_memberships"
    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    team_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), nullable=False
    )
    operator_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    valid_from: Mapped[datetime] = mapped_column(TSTZ, nullable=False)
    valid_to: Mapped[datetime | None] = mapped_column(TSTZ)
    created_at: Mapped[datetime] = mapped_column(TSTZ, server_default=func.now(), nullable=False)
    __table_args__ = (
        CheckConstraint(
            "valid_to IS NULL OR valid_to > valid_from",
            name="team_memberships_window_check",
        ),
        Index(
            "idx_team_memberships_operator_window",
            "tenant_id",
            "operator_id",
            "valid_from",
            "valid_to",
        ),
    )


class KpiConfiguration(Base):
    __tablename__ = "kpi_configurations"
    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_by: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(TSTZ, server_default=func.now(), nullable=False)
    __table_args__ = (
        UniqueConstraint("tenant_id", "version", name="kpi_configurations_tenant_version_key"),
        Index("idx_kpi_configurations_active", "tenant_id", "active"),
    )


class KpiGoal(Base):
    __tablename__ = "kpi_goals"
    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    team_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE")
    )
    metric: Mapped[str] = mapped_column(Text, nullable=False)
    target_value: Mapped[float] = mapped_column(REAL, nullable=False)
    valid_from: Mapped[datetime] = mapped_column(TSTZ, nullable=False)
    valid_to: Mapped[datetime] = mapped_column(TSTZ, nullable=False)
    created_by: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(TSTZ, server_default=func.now(), nullable=False)
    __table_args__ = (
        CheckConstraint("valid_to > valid_from", name="kpi_goals_window_check"),
        Index(
            "idx_kpi_goals_scope_window", "tenant_id", "team_id", "metric", "valid_from", "valid_to"
        ),
    )


class CrmOutcome(Base):
    __tablename__ = "crm_outcomes"
    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    external_lead_id: Mapped[str] = mapped_column(Text, nullable=False)
    call_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("calls.id", ondelete="SET NULL")
    )
    external_call_reference: Mapped[str | None] = mapped_column(Text)
    customer_id: Mapped[str | None] = mapped_column(Text)
    campaign_id: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(Text)
    channel: Mapped[str | None] = mapped_column(Text)
    owner_reference: Mapped[str | None] = mapped_column(Text)
    funnel_stage: Mapped[str | None] = mapped_column(Text)
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[int | None] = mapped_column(BigInteger)
    currency: Mapped[str | None] = mapped_column(String(8))
    product: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(TSTZ, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'")
    )
    created_at: Mapped[datetime] = mapped_column(TSTZ, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TSTZ, server_default=func.now(), nullable=False)
    __table_args__ = (
        UniqueConstraint("tenant_id", "external_lead_id", name="crm_outcomes_tenant_lead_key"),
        CheckConstraint(
            "outcome IN ('won','lost','follow_up','interested','not_qualified','unknown')",
            name="crm_outcomes_outcome_check",
        ),
        Index("idx_crm_outcomes_tenant_time", "tenant_id", "occurred_at"),
    )


class OperatorScoreRubric(Base):
    __tablename__ = "operator_score_rubrics"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    criteria: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_by: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(TSTZ, server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("tenant_id", "version", name="operator_score_rubrics_tenant_version_key"),
        Index("idx_operator_score_rubrics_active", "tenant_id", "active"),
    )


class OperatorCallScore(Base):
    __tablename__ = "operator_call_scores"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    call_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("calls.id", ondelete="CASCADE"), nullable=False
    )
    analysis_run_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("analysis_runs.id", ondelete="SET NULL")
    )
    rubric_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("operator_score_rubrics.id", ondelete="SET NULL")
    )
    operator_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    operator_label: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'queued'"))
    total_score: Mapped[float | None] = mapped_column(REAL)
    criteria_scores: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    error_detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TSTZ, server_default=func.now(), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(TSTZ)

    __table_args__ = (
        UniqueConstraint("call_id", "analysis_run_id", name="operator_call_scores_call_run_key"),
        Index("idx_operator_call_scores_tenant_operator", "tenant_id", "operator_id", "created_at"),
    )


class ChatConversation(Base):
    __tablename__ = "chat_conversations"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    owner_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    call_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("calls.id", ondelete="SET NULL")
    )
    title: Mapped[str | None] = mapped_column(Text)
    archived_at: Mapped[datetime | None] = mapped_column(TSTZ)
    pinned_at: Mapped[datetime | None] = mapped_column(TSTZ)
    created_at: Mapped[datetime] = mapped_column(TSTZ, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TSTZ, server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_chat_conversations_owner", "tenant_id", "owner_id", text("updated_at DESC")),
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    conversation_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("chat_conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    role: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'succeeded'"))
    model: Mapped[str | None] = mapped_column(Text)
    sources: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    attachments: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(TSTZ, server_default=func.now(), nullable=False)

    __table_args__ = (Index("idx_chat_messages_conversation", "conversation_id", "created_at"),)


class AssistantToolRun(Base):
    __tablename__ = "assistant_tool_runs"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    conversation_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("chat_conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_message_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("chat_messages.id", ondelete="CASCADE"), nullable=False
    )
    assistant_message_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("chat_messages.id", ondelete="SET NULL")
    )
    tool_call_id: Mapped[str] = mapped_column(String(100), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    arguments: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    result_preview: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error_code: Mapped[str | None] = mapped_column(String(80))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(TSTZ, server_default=func.now(), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(TSTZ)

    __table_args__ = (
        UniqueConstraint("conversation_id", "tool_call_id", name="assistant_tool_runs_call_key"),
        Index("idx_assistant_tool_runs_message", "user_message_id", "started_at"),
    )


class TranscriptChunk(Base):
    __tablename__ = "transcript_chunks"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    call_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("calls.id", ondelete="CASCADE"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[Any | None] = mapped_column(VectorType())
    source_revision_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("transcript_revisions.id", ondelete="SET NULL")
    )
    embedding_model: Mapped[str | None] = mapped_column(Text)
    vector_status: Mapped[str] = mapped_column(String(24), nullable=False, server_default=text("'pending'"))
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    last_attempt_at: Mapped[datetime | None] = mapped_column(TSTZ)
    next_retry_at: Mapped[datetime | None] = mapped_column(TSTZ)
    error_detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TSTZ, server_default=func.now(), nullable=False)

    __table_args__ = (UniqueConstraint("call_id", "ordinal"),)


class CallKnowledge(Base):
    __tablename__ = "call_knowledge"

    call_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("calls.id", ondelete="CASCADE"), primary_key=True
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    operator_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[Any | None] = mapped_column(VectorType())
    embedding_model: Mapped[str | None] = mapped_column(Text)
    vector_status: Mapped[str] = mapped_column(String(24), nullable=False)
    graph_status: Mapped[str] = mapped_column(String(24), nullable=False)
    indexed_at: Mapped[datetime | None] = mapped_column(TSTZ)
    error_detail: Mapped[str | None] = mapped_column(Text)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    last_attempt_at: Mapped[datetime | None] = mapped_column(TSTZ)
    next_retry_at: Mapped[datetime | None] = mapped_column(TSTZ)
    updated_at: Mapped[datetime] = mapped_column(TSTZ, server_default=func.now(), nullable=False)


class FollowUpTask(Base):
    __tablename__ = "follow_up_tasks"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    call_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("calls.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'open'"))
    priority: Mapped[str | None] = mapped_column(Text)
    due_date: Mapped[date | None] = mapped_column(Date)
    source_phone: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(TSTZ)
    completed_by: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(TSTZ, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TSTZ, server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("status IN ('open','done')", name="follow_up_tasks_status_check"),
        CheckConstraint(
            "priority IS NULL OR priority IN ('low','normal','high')",
            name="follow_up_tasks_priority_check",
        ),
        CheckConstraint("btrim(title) <> ''", name="follow_up_tasks_title_check"),
        Index("idx_follow_up_tasks_call", "call_id", "created_at"),
        Index("idx_follow_up_tasks_tenant_status", "tenant_id", "status", "due_date"),
    )


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    call_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("calls.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    run_after: Mapped[datetime] = mapped_column(TSTZ, server_default=func.now(), nullable=False)
    locked_at: Mapped[datetime | None] = mapped_column(TSTZ)
    error_code: Mapped[str | None] = mapped_column(Text)
    error_detail: Mapped[str | None] = mapped_column(Text)
    queued_at: Mapped[datetime] = mapped_column(TSTZ, server_default=func.now(), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(TSTZ)
    provider_submitted_at: Mapped[datetime | None] = mapped_column(TSTZ)
    completed_at: Mapped[datetime | None] = mapped_column(TSTZ)
    created_at: Mapped[datetime] = mapped_column(TSTZ, server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "kind IN ('asr','emotion','correction','llm','notify')", name="jobs_kind_check"
        ),
        Index(
            "idx_jobs_run",
            "status",
            "run_after",
            postgresql_where=text("status IN ('queued','failed_retryable')"),
        ),
    )


class JobOutbox(Base):
    __tablename__ = "job_outbox"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    job_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    queue_name: Mapped[str] = mapped_column(Text, nullable=False)
    function_name: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    available_at: Mapped[datetime] = mapped_column(TSTZ, server_default=func.now(), nullable=False)
    dispatched_at: Mapped[datetime | None] = mapped_column(TSTZ)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TSTZ, server_default=func.now(), nullable=False)

    __table_args__ = (
        Index(
            "idx_job_outbox_pending",
            "available_at",
            postgresql_where=text("dispatched_at IS NULL"),
        ),
    )


class ProcessingEvent(Base):
    __tablename__ = "processing_events"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    call_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("calls.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    level: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'info'"))
    status: Mapped[str | None] = mapped_column(Text)
    progress_pct: Mapped[int | None] = mapped_column(SmallInteger)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    error_code: Mapped[str | None] = mapped_column(Text)
    error_detail: Mapped[str | None] = mapped_column(Text)
    step_key: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TSTZ, server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "kind IN ('pipeline','asr','emotion','correction','llm','notify')",
            name="processing_events_kind_check",
        ),
        CheckConstraint(
            "level IN ('info','success','warning','error')",
            name="processing_events_level_check",
        ),
        CheckConstraint(
            "progress_pct IS NULL OR (progress_pct >= 0 AND progress_pct <= 100)",
            name="processing_events_progress_pct_check",
        ),
        Index("idx_processing_events_call", "call_id", "created_at"),
        Index(
            "uq_processing_events_call_step",
            "call_id",
            "step_key",
            unique=True,
            postgresql_where=text("step_key IS NOT NULL"),
        ),
    )


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    call_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), ForeignKey("calls.id"))
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    seconds_delta: Mapped[int] = mapped_column(Integer, nullable=False)
    toman_delta: Mapped[int] = mapped_column(Integer, nullable=False)
    reservation_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TSTZ, server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="ledger_entries_tenant_idem_key"),
        CheckConstraint(
            "kind IN ('topup','reservation','settlement','release','adjustment',"
            "'subscription_credit','credit_purchase','expiration','refund')",
            name="ledger_entries_kind_check",
        ),
        Index("idx_ledger_tenant_created", "tenant_id", text("created_at DESC")),
    )


class CreditReservation(Base):
    __tablename__ = "credit_reservations"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    call_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("calls.id"), nullable=False
    )
    seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    toman: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TSTZ, server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "status IN ('held','settled','released')", name="credit_reservations_status_check"
        ),
    )


class TenantBalanceCache(Base):
    __tablename__ = "tenant_balance_cache"

    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id"), primary_key=True
    )
    seconds: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    toman: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    updated_at: Mapped[datetime] = mapped_column(TSTZ, server_default=func.now(), nullable=False)


class Package(Base):
    __tablename__ = "packages"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    price_toman: Mapped[int] = mapped_column(Integer, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


class Plan(Base):
    __tablename__ = "plans"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    public: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(TSTZ, server_default=func.now(), nullable=False)


class PlanVersion(Base):
    __tablename__ = "plan_versions"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    plan_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("plans.id"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    monthly_price_toman: Mapped[int] = mapped_column(Integer, nullable=False)
    annual_price_toman: Mapped[int | None] = mapped_column(Integer)
    base_operators: Mapped[int] = mapped_column(Integer, nullable=False)
    intro_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    overage_price_per_minute_toman: Mapped[int] = mapped_column(Integer, nullable=False)
    assistant_tier: Mapped[str] = mapped_column(String(32), nullable=False)
    assistant_monthly_messages: Mapped[int] = mapped_column(Integer, nullable=False)
    assistant_source_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    assistant_model: Mapped[str | None] = mapped_column(Text)
    allows_extra_operators: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    extra_operator_monthly_toman: Mapped[int | None] = mapped_column(Integer)
    extra_operator_annual_toman: Mapped[int | None] = mapped_column(Integer)
    trial_days: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'draft'"))
    effective_at: Mapped[datetime | None] = mapped_column(TSTZ)
    published_at: Mapped[datetime | None] = mapped_column(TSTZ)
    retired_at: Mapped[datetime | None] = mapped_column(TSTZ)
    created_by: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("staff_users.id", ondelete="SET NULL")
    )

    __table_args__ = (
        UniqueConstraint("plan_id", "version", name="plan_versions_plan_version_key"),
        CheckConstraint(
            "monthly_price_toman >= 0 AND base_operators >= 0 AND intro_minutes >= 0",
            name="plan_versions_nonnegative_check",
        ),
        CheckConstraint(
            "status IN ('draft','published','retired')", name="plan_versions_status_check"
        ),
    )


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    plan_version_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("plan_versions.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    billing_period: Mapped[str] = mapped_column(String(16), nullable=False)
    period_start: Mapped[datetime] = mapped_column(TSTZ, nullable=False)
    period_end: Mapped[datetime] = mapped_column(TSTZ, nullable=False)
    cancel_at_period_end: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    next_plan_version_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("plan_versions.id")
    )
    base_operators: Mapped[int] = mapped_column(Integer, nullable=False)
    extra_operators: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    price_per_minute_toman: Mapped[int] = mapped_column(Integer, nullable=False)
    assistant_tier: Mapped[str] = mapped_column(String(32), nullable=False)
    assistant_monthly_messages: Mapped[int] = mapped_column(Integer, nullable=False)
    assistant_source_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    assistant_model: Mapped[str | None] = mapped_column(Text)
    intro_credit_issued_at: Mapped[datetime | None] = mapped_column(TSTZ)
    created_at: Mapped[datetime] = mapped_column(TSTZ, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TSTZ, server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending_payment','trialing','active','expired','canceled')",
            name="subscriptions_status_check",
        ),
        CheckConstraint(
            "billing_period IN ('trial','monthly','annual','legacy')",
            name="subscriptions_period_check",
        ),
        Index("idx_subscriptions_tenant_status", "tenant_id", "status", "period_end"),
    )


class SubscriptionExtra(Base):
    __tablename__ = "subscription_extras"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    subscription_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("subscriptions.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price_toman: Mapped[int] = mapped_column(Integer, nullable=False)
    effective_at: Mapped[datetime] = mapped_column(TSTZ, nullable=False)
    ends_at: Mapped[datetime | None] = mapped_column(TSTZ)


class SubscriptionChange(Base):
    __tablename__ = "subscription_changes"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    subscription_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("subscriptions.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    target_plan_version_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("plan_versions.id")
    )
    requested_extra_operators: Mapped[int | None] = mapped_column(Integer)
    effective_at: Mapped[datetime] = mapped_column(TSTZ, nullable=False)
    order_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(TSTZ, server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "status IN ('scheduled','pending_payment','applied','canceled','failed')",
            name="subscription_changes_status_check",
        ),
    )


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    number: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'draft'"))
    amount_toman: Mapped[int] = mapped_column(Integer, nullable=False)
    callback_token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    customer_name: Mapped[str] = mapped_column(Text, nullable=False)
    customer_email: Mapped[str] = mapped_column(CITEXT, nullable=False)
    customer_mobile: Mapped[str] = mapped_column(String(20), nullable=False)
    invoice_profile: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'")
    )
    terms_version: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'1'")
    )
    created_at: Mapped[datetime] = mapped_column(TSTZ, server_default=func.now(), nullable=False)
    paid_at: Mapped[datetime | None] = mapped_column(TSTZ)

    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="orders_tenant_idem_key"),
        CheckConstraint(
            "status IN ('draft','pending_payment','paid','canceled',"
            "'partially_refunded','refunded')",
            name="orders_status_check",
        ),
    )


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    order_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price_toman: Mapped[int] = mapped_column(Integer, nullable=False)
    total_toman: Mapped[int] = mapped_column(Integer, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'")
    )


class PaymentAttempt(Base):
    __tablename__ = "payment_attempts"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    order_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("orders.id"), nullable=False
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    gateway: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    amount_rial: Mapped[int] = mapped_column(BigInteger, nullable=False)
    authority: Mapped[str | None] = mapped_column(String(64), unique=True)
    ref_id: Mapped[str | None] = mapped_column(String(64))
    response_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'")
    )
    created_at: Mapped[datetime] = mapped_column(TSTZ, server_default=func.now(), nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(TSTZ)

    __table_args__ = (
        CheckConstraint(
            "status IN ('redirected','canceled','pending_verification','failed','verified')",
            name="payment_attempts_status_check",
        ),
    )


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    order_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("orders.id"), unique=True, nullable=False
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    number: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    amount_toman: Mapped[int] = mapped_column(Integer, nullable=False)
    profile_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    issued_at: Mapped[datetime] = mapped_column(TSTZ, server_default=func.now(), nullable=False)


class Refund(Base):
    __tablename__ = "refunds"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    order_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("orders.id"), nullable=False
    )
    payment_attempt_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("payment_attempts.id")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    amount_toman: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    method: Mapped[str] = mapped_column(String(24), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    gateway_reference: Mapped[str | None] = mapped_column(String(128))
    response_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'")
    )
    created_by: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("staff_users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(TSTZ, server_default=func.now(), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(TSTZ)

    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="refunds_tenant_idem_key"),
        CheckConstraint("amount_toman > 0", name="refunds_amount_check"),
        CheckConstraint("status IN ('pending','completed','failed')", name="refunds_status_check"),
        CheckConstraint("method IN ('reverse','manual')", name="refunds_method_check"),
    )


class CreditGrant(Base):
    __tablename__ = "credit_grants"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    total_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    remaining_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(TSTZ)
    created_at: Mapped[datetime] = mapped_column(TSTZ, server_default=func.now(), nullable=False)
    __table_args__ = (
        Index("idx_credit_grants_available", "tenant_id", "expires_at", "created_at"),
    )


class ReservationAllocation(Base):
    __tablename__ = "reservation_allocations"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    reservation_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("credit_reservations.id", ondelete="CASCADE"),
        nullable=False,
    )
    grant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("credit_grants.id"), nullable=False
    )
    seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    __table_args__ = (
        UniqueConstraint("reservation_id", "grant_id", name="reservation_allocations_key"),
    )


class AssistantUsage(Base):
    __tablename__ = "assistant_usage"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    user_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    message_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("chat_messages.id", ondelete="SET NULL")
    )
    period_start: Mapped[datetime] = mapped_column(TSTZ, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    model: Mapped[str | None] = mapped_column(Text)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(TSTZ, server_default=func.now(), nullable=False)
    __table_args__ = (Index("idx_assistant_usage_period", "tenant_id", "period_start", "status"),)


class InstallationRequest(Base):
    __tablename__ = "installation_requests"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    order_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), ForeignKey("orders.id"))
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    pbx_type: Mapped[str] = mapped_column(Text, nullable=False)
    pbx_version: Mapped[str | None] = mapped_column(Text)
    extension_count: Mapped[int] = mapped_column(Integer, nullable=False)
    connection_method: Mapped[str] = mapped_column(Text, nullable=False)
    technical_contact: Mapped[str] = mapped_column(Text, nullable=False)
    preferred_time: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    internal_notes: Mapped[str | None] = mapped_column(Text)
    scheduled_at: Mapped[datetime | None] = mapped_column(TSTZ)
    created_at: Mapped[datetime] = mapped_column(TSTZ, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TSTZ, server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "status IN ('requested','paid','reviewing','scheduled',"
            "'in_progress','completed','canceled')",
            name="installation_requests_status_check",
        ),
    )


class ContactLead(Base):
    __tablename__ = "contact_leads"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    organization: Mapped[str] = mapped_column(Text, nullable=False)
    mobile: Mapped[str] = mapped_column(String(20), nullable=False)
    email: Mapped[str] = mapped_column(CITEXT, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=text("'contact_page'")
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False, server_default=text("'new'"))
    owner_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("staff_users.id", ondelete="SET NULL")
    )
    internal_notes: Mapped[str | None] = mapped_column(Text)
    follow_up_at: Mapped[datetime | None] = mapped_column(TSTZ)
    created_at: Mapped[datetime] = mapped_column(TSTZ, server_default=func.now(), nullable=False)


class SignupOtp(Base):
    __tablename__ = "signup_otps"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    mobile: Mapped[str] = mapped_column(String(20), nullable=False)
    email: Mapped[str] = mapped_column(CITEXT, nullable=False)
    code_hash: Mapped[str] = mapped_column(Text, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    expires_at: Mapped[datetime] = mapped_column(TSTZ, nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(TSTZ)
    created_at: Mapped[datetime] = mapped_column(TSTZ, server_default=func.now(), nullable=False)


class TrialClaim(Base):
    __tablename__ = "trial_claims"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    email: Mapped[str] = mapped_column(CITEXT, unique=True, nullable=False)
    mobile: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TSTZ, server_default=func.now(), nullable=False)


class Webhook(Base):
    __tablename__ = "webhooks"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    secret: Mapped[str] = mapped_column(Text, nullable=False)
    events: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    webhook_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("webhooks.id"), nullable=False
    )
    tenant_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), ForeignKey("tenants.id"))
    call_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    event: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer)
    next_retry_at: Mapped[datetime | None] = mapped_column(TSTZ)
    created_at: Mapped[datetime] = mapped_column(TSTZ, server_default=func.now(), nullable=False)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    actor_type: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    tenant_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    action: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'")
    )
    ip: Mapped[str | None] = mapped_column(INET)
    created_at: Mapped[datetime] = mapped_column(TSTZ, server_default=func.now(), nullable=False)


class PlatformSetting(Base):
    __tablename__ = "platform_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TSTZ, server_default=func.now(), nullable=False)


class TenantDatabaseRegistry(Base):
    __tablename__ = "tenant_database_registry"

    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    database_name: Mapped[str] = mapped_column(String(63), unique=True, nullable=False)
    runtime_role: Mapped[str] = mapped_column(String(63), unique=True, nullable=False)
    encrypted_dsn: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    schema_revision: Mapped[str | None] = mapped_column(String(128))
    graph_name: Mapped[str] = mapped_column(
        String(63), nullable=False, server_default=text("'tenant_graph'")
    )
    last_health_at: Mapped[datetime | None] = mapped_column(TSTZ)
    activated_at: Mapped[datetime | None] = mapped_column(TSTZ)
    quarantine_until: Mapped[datetime | None] = mapped_column(TSTZ)
    created_at: Mapped[datetime] = mapped_column(TSTZ, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TSTZ, server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "status IN ('provisioning','ready','maintenance','quarantined','failed')",
            name="tenant_database_registry_status_check",
        ),
    )


class TenantProvisioningJob(Base):
    __tablename__ = "tenant_provisioning_jobs"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'pending'")
    )
    step: Mapped[str] = mapped_column(String(64), nullable=False, server_default=text("'pending'"))
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    error_detail: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(TSTZ)
    completed_at: Mapped[datetime | None] = mapped_column(TSTZ)
    created_at: Mapped[datetime] = mapped_column(TSTZ, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TSTZ, server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','running','retryable','failed','succeeded')",
            name="tenant_provisioning_jobs_status_check",
        ),
        Index("idx_tenant_provisioning_claim", "status", "created_at"),
    )


class TenantDataMigration(Base):
    __tablename__ = "tenant_data_migrations"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'pending'")
    )
    phase: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=text("'prechecking'")
    )
    manifest: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'")
    )
    checkpoint: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'")
    )
    error_detail: Mapped[str | None] = mapped_column(Text)
    source_locked_at: Mapped[datetime | None] = mapped_column(TSTZ)
    cutover_at: Mapped[datetime | None] = mapped_column(TSTZ)
    rollback_until: Mapped[datetime | None] = mapped_column(TSTZ)
    completed_at: Mapped[datetime | None] = mapped_column(TSTZ)
    created_at: Mapped[datetime] = mapped_column(TSTZ, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TSTZ, server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("tenant_id", name="tenant_data_migrations_tenant_key"),
        Index("idx_tenant_data_migrations_status", "status", "created_at"),
    )


class IdentityProjectionOutbox(Base):
    __tablename__ = "identity_projection_outbox"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    operation: Mapped[str] = mapped_column(String(16), nullable=False)
    version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    available_at: Mapped[datetime] = mapped_column(TSTZ, nullable=False, server_default=func.now())
    applied_at: Mapped[datetime | None] = mapped_column(TSTZ)
    error_detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TSTZ, server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "operation IN ('upsert','delete')", name="identity_projection_operation_check"
        ),
        UniqueConstraint("tenant_id", "user_id", "version", name="identity_projection_version_key"),
        Index("idx_identity_projection_pending", "applied_at", "available_at", "created_at"),
    )


class TenantBackup(Base):
    __tablename__ = "tenant_backups"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, server_default=text("'running'")
    )
    object_key: Mapped[str | None] = mapped_column(Text)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    schema_revision: Mapped[str | None] = mapped_column(String(128))
    error_detail: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(TSTZ, server_default=func.now(), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(TSTZ)
    expires_at: Mapped[datetime | None] = mapped_column(TSTZ)

    __table_args__ = (
        CheckConstraint(
            "status IN ('running','succeeded','failed','expired')",
            name="tenant_backups_status_check",
        ),
        Index("idx_tenant_backups_tenant_started", "tenant_id", "started_at"),
    )


class IdentityProjectionState(Base):
    __tablename__ = "identity_projection_state"

    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    applied_at: Mapped[datetime] = mapped_column(TSTZ, server_default=func.now(), nullable=False)


TENANT_TABLES: tuple[str, ...] = (
    "users",
    "api_keys",
    "audio_objects",
    "calls",
    "call_operator_assignments",
    "utterances",
    "transcripts",
    "analysis_runs",
    "analysis_steps",
    "call_insights",
    "sales_insights",
    "teams",
    "team_memberships",
    "kpi_configurations",
    "kpi_goals",
    "crm_outcomes",
    "operator_score_rubrics",
    "operator_call_scores",
    "chat_conversations",
    "chat_messages",
    "assistant_tool_runs",
    "transcript_chunks",
    "call_knowledge",
    "follow_up_tasks",
    "jobs",
    "job_outbox",
    "processing_events",
    "ledger_entries",
    "credit_reservations",
    "tenant_balance_cache",
    "subscriptions",
    "subscription_extras",
    "subscription_changes",
    "orders",
    "order_items",
    "payment_attempts",
    "invoices",
    "refunds",
    "credit_grants",
    "reservation_allocations",
    "assistant_usage",
    "installation_requests",
    "trial_claims",
    "webhooks",
    "webhook_deliveries",
)
