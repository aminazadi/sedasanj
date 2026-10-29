from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    HttpUrl,
    field_validator,
    model_validator,
)

from app.sentiment import delta_and_trajectory, normalize_sentiment, valence

Sentiment = Literal["angry", "sad", "neutral", "satisfied", "happy"]
SentimentTrajectory = Literal["improved", "worsened", "stable"]
Intent = Literal[
    "technical_support",
    "sales_inquiry",
    "complaint",
    "consultation",
    "billing",
    "other",
]
WebhookEvent = Literal["call.complete", "call.failed", "balance.low", "sales.insight"]
CallType = Literal["answered", "no_answer", "busy", "congestion", "failed", "canceled", "voicemail"]
UnansweredCallType = Literal["no_answer", "busy", "congestion", "failed", "canceled"]


def _normalize_sentiment(value: object) -> object:
    return normalize_sentiment(value)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    totp_code: str | None = None


class TotpCheck(BaseModel):
    code: str


class TotpDisable(BaseModel):
    password: str
    code: str


class TotpSetup(BaseModel):
    secret: str
    uri: str


class TotpStatus(BaseModel):
    enabled: bool


class LoginStep(BaseModel):
    requires_totp: bool


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshRequest(BaseModel):
    refresh_token: str


ArchiveFormat = Literal["wav", "gzip", "zip"]


class ApiKeyCreate(BaseModel):
    label: str | None = Field(default=None, max_length=120)
    archive_format: Literal["gzip", "zip"] = "gzip"
    archive_password: str | None = Field(default=None, min_length=12, max_length=128)

    @model_validator(mode="after")
    def _validate_archive_password(self) -> ApiKeyCreate:
        if self.archive_format != "zip" and self.archive_password is not None:
            raise ValueError("archive_password is only supported for zip")
        return self


class ApiKeyUpdate(BaseModel):
    label: str | None = Field(default=None, max_length=120)
    archive_format: Literal["gzip", "zip"] | None = None
    archive_password: str | None = Field(default=None, min_length=12, max_length=128)
    remove_archive_password: bool = False

    @model_validator(mode="after")
    def _validate_archive_password(self) -> ApiKeyUpdate:
        if self.archive_password is not None and self.remove_archive_password:
            raise ValueError("cannot set and remove archive_password together")
        if self.archive_format == "gzip" and self.archive_password is not None:
            raise ValueError("archive_password is only supported for zip")
        return self


class ApiKeyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    key_prefix: str
    label: str | None
    archive_format: ArchiveFormat
    archive_password_configured: bool = False
    last_used_at: datetime | None
    created_at: datetime


class ApiKeyCreated(ApiKeyOut):
    secret: str


class IngestAccepted(BaseModel):
    call_id: UUID
    status: str
    reservation_id: UUID | None


class VoicemailIngestMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asterisk_uniqueid: str = Field(min_length=1, max_length=255)
    mailbox: str = Field(min_length=1, max_length=80)
    context: str = Field(default="default", min_length=1, max_length=120)
    folder: str = Field(min_length=1, max_length=80)
    message_id: str | None = Field(default=None, max_length=255)
    caller_number: str | None = Field(default=None, max_length=80)
    started_at: datetime


class MissedCallIngest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asterisk_uniqueid: str = Field(min_length=1, max_length=255)
    call_type: UnansweredCallType = "no_answer"
    caller_number: str = Field(min_length=1, max_length=80)
    dialed_number: str = Field(min_length=1, max_length=80)
    started_at: datetime
    ended_at: datetime
    direction: Literal["inbound", "outbound", "internal"] | None = None
    agent_extension: str | None = Field(default=None, max_length=80)
    campaign_id: str | None = Field(default=None, max_length=120)
    source: str | None = Field(default=None, max_length=120)
    external_reference: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def _validate_window(self) -> MissedCallIngest:
        if self.ended_at < self.started_at:
            raise ValueError("ended_at must not be earlier than started_at")
        return self


class IngestConfigValidation(BaseModel):
    status: Literal["ok"] = "ok"
    tenant: str | None
    tenant_id: UUID
    balance_seconds: int
    balance_minutes: float
    server_time: datetime
    archive_format: ArchiveFormat
    archive_password_configured: bool
    archive_password_valid: bool


class SentimentPhrase(BaseModel):
    text: str = Field(validation_alias=AliasChoices("text", "phrase"))
    sentiment: Sentiment

    @field_validator("sentiment", mode="before")
    @classmethod
    def _coerce_phrase_sentiment(cls, value: object) -> object:
        return _normalize_sentiment(value)


class SentimentPoint(BaseModel):
    label: Sentiment = Field(validation_alias=AliasChoices("label", "sentiment", "overall"))
    score: float = Field(default=0.5, ge=0.0, le=1.0)

    @field_validator("label", mode="before")
    @classmethod
    def _coerce_label(cls, value: object) -> object:
        return _normalize_sentiment(value)


class SentimentWindow(BaseModel):
    t_start_ms: int = Field(ge=0)
    t_end_ms: int = Field(ge=0)
    label: Sentiment
    score: float = Field(ge=0.0, le=1.0)
    valence: float = Field(ge=0.0, le=1.0)

    @field_validator("label", mode="before")
    @classmethod
    def _coerce_label(cls, value: object) -> object:
        return _normalize_sentiment(value)

    @model_validator(mode="after")
    def _validate_interval(self) -> SentimentWindow:
        if self.t_end_ms <= self.t_start_ms:
            raise ValueError("sentiment window end must be after start")
        return self


def _coerce_sentiment_point(value: object) -> object:
    if isinstance(value, str):
        return {"label": value, "score": 0.5}
    return value


class PartySentiment(BaseModel):
    """Start / end / whole-call sentiment for one stereo channel."""

    start: SentimentPoint
    end: SentimentPoint
    overall: SentimentPoint
    delta: float = 0.0
    trajectory: SentimentTrajectory = "stable"
    timeline: list[SentimentWindow] = Field(default_factory=list)

    @field_validator("start", "end", "overall", mode="before")
    @classmethod
    def _coerce_points(cls, value: object) -> object:
        return _coerce_sentiment_point(value)

    @model_validator(mode="after")
    def _complete_delta(self) -> PartySentiment:
        delta, trajectory = delta_and_trajectory(
            self.start.label, self.start.score, self.end.label, self.end.score
        )
        self.delta = delta
        self.trajectory = trajectory
        return self

    @property
    def start_valence(self) -> float:
        return valence(self.start.label, self.start.score)

    @property
    def end_valence(self) -> float:
        return valence(self.end.label, self.end.score)


class DualPartySentiment(BaseModel):
    caller: PartySentiment
    agent: PartySentiment | None = None

    @field_validator("agent", mode="before")
    @classmethod
    def _empty_agent(cls, value: object) -> object:
        if value in (None, {}, []):
            return None
        return value


class SentimentProfile(BaseModel):
    """Parallel text and (optional) voice analyses for the same call."""

    text: DualPartySentiment | None = None
    voice: DualPartySentiment | None = None
    voice_model: str | None = None


class SentimentBlock(BaseModel):
    overall: Sentiment
    score: float = Field(ge=0.0, le=1.0)
    phrases: list[SentimentPhrase] = Field(default_factory=list)
    caller: PartySentiment | None = None
    agent: PartySentiment | None = None

    @model_validator(mode="before")
    @classmethod
    def _coerce_object_overall(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        overall = value.get("overall")
        if not isinstance(overall, dict):
            return value
        normalized = dict(value)
        normalized["overall"] = overall.get(
            "label", overall.get("sentiment", overall.get("overall"))
        )
        if normalized.get("score") is None and overall.get("score") is not None:
            normalized["score"] = overall["score"]
        return normalized

    @field_validator("overall", mode="before")
    @classmethod
    def _coerce_overall(cls, value: object) -> object:
        return _normalize_sentiment(value)

    @field_validator("agent", mode="before")
    @classmethod
    def _empty_agent(cls, value: object) -> object:
        if value in (None, {}, []):
            return None
        return value

    @model_validator(mode="after")
    def _fill_parties(self) -> SentimentBlock:
        if self.caller is None:
            point = SentimentPoint(label=self.overall, score=self.score)
            self.caller = PartySentiment(start=point, end=point, overall=point)
        self.overall = self.caller.overall.label
        self.score = self.caller.overall.score
        return self

    def profile(self) -> SentimentProfile:
        assert self.caller is not None
        return SentimentProfile(
            text=DualPartySentiment(caller=self.caller, agent=self.agent),
            voice=None,
        )


class NerBlock(BaseModel):
    persons: list[str] = Field(default_factory=list)
    dates: list[str] = Field(default_factory=list)
    amounts: list[str] = Field(default_factory=list)
    phone_numbers: list[str] = Field(default_factory=list)
    organizations: list[str] = Field(default_factory=list)


class SalesEvidence(BaseModel):
    text: str = Field(max_length=500)
    t_start_ms: int | None = Field(default=None, ge=0)
    t_end_ms: int | None = Field(default=None, ge=0)


class SalesBlock(BaseModel):
    funnel_stage: Literal[
        "all_calls",
        "effective",
        "qualified",
        "interested",
        "follow_up",
        "proposal",
        "won",
        "lost",
        "unknown",
    ] = "unknown"
    outcome: Literal["won", "lost", "follow_up", "interested", "not_qualified", "unknown"] = (
        "unknown"
    )
    certainty: Literal["explicit", "probable", "unknown"] = "unknown"
    confidence: float = Field(default=0, ge=0, le=1)
    product: str | None = Field(default=None, max_length=200)
    objections: list[str] = Field(default_factory=list, max_length=8)
    win_loss_reason: str | None = Field(default=None, max_length=500)
    next_action: str | None = Field(default=None, max_length=500)
    next_action_due_at: datetime | None = None
    evidence: list[SalesEvidence] = Field(default_factory=list, max_length=5)


class ExtractionResult(BaseModel):
    """§9.2 LLM output contract."""

    summary: str
    keywords: list[str] = Field(default_factory=list)
    sentiment: SentimentBlock
    intent: Intent
    ner: NerBlock = Field(default_factory=NerBlock)
    action_items: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    sales: SalesBlock = Field(default_factory=SalesBlock)

    @field_validator("keywords")
    @classmethod
    def _cap_keywords(cls, value: list[str]) -> list[str]:
        return value[:5]

    @field_validator("topics")
    @classmethod
    def _cap_topics(cls, value: list[str]) -> list[str]:
        return value[:3]

    @field_validator("ner", mode="before")
    @classmethod
    def _coerce_ner(cls, value: object) -> object:
        if value is None or value == []:
            return {}
        return value


class UtteranceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    channel: int
    t_start_ms: int
    t_end_ms: int
    text: str
    source_text: str | None = None
    uncertain: bool = False


class CorrectionStatusOut(BaseModel):
    id: UUID
    status: Literal["queued", "running", "validating", "succeeded", "failed"]
    trigger: Literal["automatic", "manual"]
    mode: Literal["text_only", "audio_only", "two_stage"]
    audio_models: list[str] = Field(default_factory=list)
    text_models: list[str] = Field(default_factory=list)
    provider_model: str | None = None
    error_code: str | None = None
    error_detail: str | None = None
    uncertain_items: list[dict[str, Any]] = Field(default_factory=list)
    uncertain_count: int = 0
    uncertain_ratio: float = 0.0
    queued_at: datetime
    started_at: datetime | None = None
    provider_submitted_at: datetime | None = None
    completed_at: datetime | None = None


class AsrTranscriptRevisionOut(BaseModel):
    id: UUID
    status: Literal["queued", "running", "succeeded", "failed"]
    trigger: Literal["initial", "manual"]
    full_text: str | None = None
    asr_model: str | None = None
    asr_version: str | None = None
    speaker_mode: str | None = None
    timestamp_source: str | None = None
    error_code: str | None = None
    error_detail: str | None = None
    created_at: datetime
    completed_at: datetime | None = None
    activated_at: datetime | None = None
    active: bool = False
    correction_status: Literal["queued", "running", "validating", "succeeded", "failed"] | None = None
    utterances: list[UtteranceOut] = Field(default_factory=list)
    corrected_utterances: list[UtteranceOut] = Field(default_factory=list)


class InsightsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    summary: str | None = None
    keywords: list[str] | None = None
    sentiment: Sentiment | None = None
    sentiment_score: float | None = None
    sentiment_profile: SentimentProfile | None = None
    intent: str | None = None
    topics: list[str] | None = None
    ner: dict[str, Any] | None = None
    action_items: Any | None = None

    @field_validator("sentiment", mode="before")
    @classmethod
    def _coerce_legacy_sentiment(cls, value: object) -> object:
        return _normalize_sentiment(value) if value is not None else None

    @model_validator(mode="after")
    def _fill_legacy_sentiment_profile(self) -> InsightsOut:
        if self.sentiment_profile is None and self.sentiment is not None:
            point = SentimentPoint(label=self.sentiment, score=self.sentiment_score or 0.0)
            self.sentiment_profile = SentimentProfile(
                text=DualPartySentiment(
                    caller=PartySentiment(start=point, end=point, overall=point)
                )
            )
        return self


class ScoreCriterionIn(BaseModel):
    title: str = Field(min_length=2, max_length=80)
    description: str = Field(min_length=2, max_length=500)
    weight: int = Field(ge=1, le=100)
    levels: list[str] = Field(min_length=5, max_length=5)

    @field_validator("levels")
    @classmethod
    def _distinct_levels(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value) or len({item.strip() for item in value}) != 5:
            raise ValueError("levels must contain five distinct descriptions")
        return [item.strip() for item in value]


class ScoreRubricCreate(BaseModel):
    criteria: list[ScoreCriterionIn] = Field(min_length=2, max_length=8)

    @model_validator(mode="after")
    def _weights_total(self) -> ScoreRubricCreate:
        if sum(item.weight for item in self.criteria) != 100:
            raise ValueError("criteria weights must total 100")
        return self


class ScoreRubricOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    version: int
    criteria: list[dict[str, Any]]
    active: bool
    created_at: datetime


class OperatorCallScoreOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    call_id: UUID
    operator_id: UUID | None
    operator_label: str
    status: str
    total_score: float | None
    criteria_scores: list[dict[str, Any]] | None = None
    created_at: datetime
    completed_at: datetime | None = None


class OperatorScoreSummary(BaseModel):
    operator_id: UUID | None
    operator_label: str
    average_score: float | None
    scored_calls: int
    rank: int | None = None


class OperatorScoreReport(BaseModel):
    from_date: datetime | None
    to_date: datetime | None
    ranking_visible: bool
    items: list[OperatorScoreSummary]
    total: int


class RankingVisibilityUpdate(BaseModel):
    operator_ranking_visible: bool


class ChatConversationCreate(BaseModel):
    call_id: UUID | None = None
    mode: Literal["normal", "training"] = "normal"


class ChatConversationUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    archived: bool | None = None
    pinned: bool | None = None

    @model_validator(mode="after")
    def _require_change(self) -> ChatConversationUpdate:
        if self.title is None and self.archived is None and self.pinned is None:
            raise ValueError("at least one conversation change is required")
        if self.archived is True and self.pinned is True:
            raise ValueError("an archived conversation cannot be pinned")
        return self


class ChatConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    call_id: UUID | None
    mode: Literal["normal", "training"]
    title: str | None
    archived_at: datetime | None
    pinned_at: datetime | None
    created_at: datetime
    updated_at: datetime


class OrganizationMemoryUpdate(BaseModel):
    lock_version: int = Field(ge=1)
    category: Literal["organization_profile", "products_services", "terminology", "policies", "analysis_rules", "freeform"] | None = None
    title: str | None = Field(default=None, min_length=1, max_length=200)
    content: str | None = Field(default=None, min_length=1, max_length=12_000)
    structured_payload: dict[str, Any] | None = None
    tags: list[str] | None = Field(default=None, max_length=30)
    applies_to: list[Literal["assistant", "correction", "analysis", "scoring"]] | None = Field(default=None, min_length=1, max_length=4)


class OrganizationMemoryAction(BaseModel):
    lock_version: int = Field(ge=1)
    idempotency_key: str | None = Field(default=None, max_length=120)


class OrganizationMemoryMerge(BaseModel):
    memory_ids: list[UUID] = Field(min_length=2, max_length=10)
    lock_versions: dict[UUID, int]
    logical_key: str = Field(min_length=1, max_length=120)
    category: Literal["organization_profile", "products_services", "terminology", "policies", "analysis_rules", "freeform"]
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=12_000)
    structured_payload: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list, max_length=30)
    applies_to: list[Literal["assistant", "correction", "analysis", "scoring"]] = Field(min_length=1, max_length=4)
    idempotency_key: str | None = Field(default=None, max_length=120)


class OrganizationMemoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    logical_key: str
    version: int
    supersedes_id: UUID | None
    category: str
    title: str
    content: str
    structured_payload: dict[str, Any]
    tags: list[str]
    applies_to: list[str]
    status: str
    source_conversation_id: UUID | None
    source_message_id: UUID | None
    created_by: UUID | None
    approved_by: UUID | None
    lock_version: int
    created_at: datetime
    updated_at: datetime
    approved_at: datetime | None
    archived_at: datetime | None
    conflicts: list[UUID] = Field(default_factory=list)


class AssistantMessageAttachments(BaseModel):
    operator_id: UUID | None = None
    conversation_ids: list[UUID] = Field(default_factory=list, max_length=5)
    from_date: datetime | None = None
    to_date: datetime | None = None
    tool_names: list[str] = Field(default_factory=list, max_length=7)

    @model_validator(mode="after")
    def _validate_window(self) -> AssistantMessageAttachments:
        if (self.from_date is None) != (self.to_date is None):
            raise ValueError("both from_date and to_date are required")
        if self.from_date is not None and self.from_date >= self.to_date:
            raise ValueError("from_date must be earlier than to_date")
        if len(set(self.conversation_ids)) != len(self.conversation_ids):
            raise ValueError("conversation_ids must be unique")
        if len(set(self.tool_names)) != len(self.tool_names):
            raise ValueError("tool_names must be unique")
        return self


class ChatMessageCreate(BaseModel):
    content: str = Field(min_length=2, max_length=4000)
    attachments: AssistantMessageAttachments = Field(default_factory=AssistantMessageAttachments)


class EphemeralChatHistoryItem(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=1500)


class EphemeralChatMessageCreate(ChatMessageCreate):
    call_id: UUID | None = None
    history: list[EphemeralChatHistoryItem] = Field(default_factory=list, max_length=24)


class ChatMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    role: str
    content: str
    status: str
    model: str | None = None
    sources: list[dict[str, Any]] | None = None
    attachments: AssistantMessageAttachments | None = None
    tool_runs: list[dict[str, Any]] = Field(default_factory=list)
    memory_drafts: list[OrganizationMemoryOut] = Field(default_factory=list)
    created_at: datetime


class CallSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    asterisk_uniqueid: str
    caller_number: str | None
    dialed_number: str | None
    direction: str | None
    agent_extension: str | None
    started_at: datetime
    ended_at: datetime
    updated_at: datetime
    duration_ms: int
    call_type: CallType = "answered"
    voicemail_context: str | None = None
    voicemail_folder: str | None = None
    voicemail_message_id: str | None = None
    billed_seconds: int | None
    status: str
    error_code: str | None
    progress_pct: int = 0
    progress_detail: str | None = None
    processing: bool = False
    recovery_pending: bool = False
    summary: str | None = None
    sentiment: Sentiment | None = None
    sentiment_trajectory: SentimentTrajectory | None = None
    intent: str | None = None
    caller_name: str | None = None
    dialed_name: str | None = None

    @field_validator("sentiment", mode="before")
    @classmethod
    def _coerce_sentiment(cls, value: object) -> object:
        if value in (None, ""):
            return None
        return _normalize_sentiment(value)


class CallPage(BaseModel):
    items: list[CallSummary]
    next_cursor: str | None = None
    total: int
    page: int
    page_size: int
    pages: int


class ProcessingEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: str
    level: str
    status: str | None
    progress_pct: int | None
    message: str
    error_code: str | None
    error_detail: str | None
    step_key: str | None = None
    created_at: datetime


TaskStatus = Literal["open", "done"]
TaskPriority = Literal["low", "normal", "high"]


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    call_id: UUID
    title: str
    description: str | None = None
    status: TaskStatus
    priority: TaskPriority | None = None
    due_date: date | None = None
    source_phone: str | None = None
    caller_number: str | None = None
    dialed_number: str | None = None
    agent_extension: str | None = None
    created_at: datetime
    completed_at: datetime | None = None
    updated_at: datetime


class TaskUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=500)
    description: str | None = Field(default=None, max_length=4000)
    status: TaskStatus | None = None
    priority: TaskPriority | None = None
    due_date: date | None = None


class TaskDay(BaseModel):
    date: date
    items: list[TaskOut]


class TaskBoard(BaseModel):
    today: list[TaskOut]
    upcoming: list[TaskDay]
    completed: list[TaskOut]
    open_count: int
    today_count: int
    upcoming_count: int
    completed_count: int


class CallDetail(CallSummary):
    audio_available: bool = False
    can_retry_transcription: bool = False
    transcript: str | None = None
    corrected_transcript: str | None = None
    corrected_transcript_at: datetime | None = None
    asr_model: str | None = None
    active_asr_revision_id: UUID | None = None
    speaker_mode: str | None = None
    utterances: list[UtteranceOut] = Field(default_factory=list)
    raw_utterances: list[UtteranceOut] = Field(default_factory=list)
    speaker_labels: dict[int, str] = Field(default_factory=dict)
    correction: CorrectionStatusOut | None = None
    insights: InsightsOut | None = None
    sales: SalesBlock | None = None
    tasks: list[TaskOut] = Field(default_factory=list)
    analysis_run_id: UUID | None = None
    prompt_version: str | None = None
    llm_model: str | None = None
    memory_sha256: str | None = None
    memory_versions: list[dict[str, Any]] = Field(default_factory=list)
    error_detail: str | None = None
    processing_events: list[ProcessingEventOut] = Field(default_factory=list)


class AnalyticsBucket(BaseModel):
    key: str
    count: int


class AnalyticsTrendPoint(BaseModel):
    date: str
    missed_calls: int = 0
    voicemail_calls: int = 0
    call_types: dict[str, int] = Field(default_factory=dict)
    angry: int = 0
    sad: int = 0
    neutral: int = 0
    satisfied: int = 0
    happy: int = 0


class AnalyticsSummary(BaseModel):
    from_date: datetime
    to_date: datetime
    total_calls: int
    answered_calls: int = 0
    missed_calls: int = 0
    voicemail_calls: int = 0
    voicemail_duration_ms: int = 0
    voicemail_transcribed: int = 0
    voicemail_transcription_rate: float = 0
    call_types: list[AnalyticsBucket] = Field(default_factory=list)
    total_minutes: float
    intents: list[AnalyticsBucket]
    sentiments: list[AnalyticsBucket]
    caller_trajectories: list[AnalyticsBucket] = Field(default_factory=list)
    agent_sentiments: list[AnalyticsBucket] = Field(default_factory=list)
    agent_trajectories: list[AnalyticsBucket] = Field(default_factory=list)
    trend: list[AnalyticsTrendPoint]


class BalanceOut(BaseModel):
    seconds: int
    minutes: float
    toman: int
    price_per_minute_toman: int
    expiring_seconds: int = 0
    purchased_seconds: int = 0
    next_expiration_at: datetime | None = None


class LedgerEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    call_id: UUID | None
    kind: str
    seconds_delta: int
    toman_delta: int
    created_at: datetime


class PackageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    minutes: int
    price_toman: int
    active: bool


class WebhookCreate(BaseModel):
    url: HttpUrl
    events: list[WebhookEvent] = Field(min_length=1)
    secret: str | None = None


class WebhookOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    url: str
    events: list[str]
    active: bool


class WebhookCreated(WebhookOut):
    secret: str


def _blank_to_none(value: object) -> object:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    role: Literal["org_admin", "operator", "viewer"]
    mobile_number: str | None = None
    extension: str | None = None
    display_name: str | None = Field(default=None, max_length=120)

    @field_validator("mobile_number", "extension", mode="before")
    @classmethod
    def _optional_number(cls, value: object) -> object:
        return _blank_to_none(value)

    @model_validator(mode="after")
    def _operator_needs_a_number(self) -> UserCreate:
        if self.role == "operator" and not (self.mobile_number or self.extension):
            raise ValueError("an operator must have a mobile number or an internal extension")
        return self


class UserUpdate(BaseModel):
    role: Literal["org_admin", "operator", "viewer"] | None = None
    mobile_number: str | None = None
    extension: str | None = None
    password: str | None = Field(default=None, min_length=8)
    display_name: str | None = Field(default=None, max_length=120)
    profile_context: str | None = Field(default=None, max_length=2000)

    @field_validator("mobile_number", "extension", mode="before")
    @classmethod
    def _optional_number(cls, value: object) -> object:
        return _blank_to_none(value)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    role: str
    mobile_number: str | None = None
    extension: str | None = None
    display_name: str | None = None
    profile_context: str | None = None
    created_at: datetime


class ProfileUpdate(BaseModel):
    display_name: str = Field(min_length=2, max_length=120)
    mobile_number: str | None = Field(default=None, max_length=32)
    extension: str | None = Field(default=None, max_length=32)
    profile_context: str | None = Field(default=None, max_length=2000)

    @field_validator("display_name", "mobile_number", "extension", "profile_context", mode="before")
    @classmethod
    def _trim_profile_values(cls, value: object) -> object:
        return _blank_to_none(value)


class TenantCreate(BaseModel):
    name: str
    admin_email: EmailStr
    admin_password: str = Field(min_length=8)
    timezone: str = "Asia/Tehran"
    audio_retention_days: int = 30
    max_concurrent_jobs: int = 10
    max_operators: int = Field(default=5, ge=0)
    plan_code: str = Field(default="legacy_custom", pattern=r"^[a-z0-9_]{2,32}$")
    billing_period: Literal["annual", "legacy"] = "annual"
    subscription_days: int | None = Field(default=None, ge=1, le=3660)


class TenantUpdate(BaseModel):
    name: str | None = None
    max_concurrent_jobs: int | None = None
    audio_retention_days: int | None = None
    timezone: str | None = None
    max_operators: int | None = Field(default=None, ge=0)


class TenantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    status: str
    timezone: str
    max_concurrent_jobs: int
    audio_retention_days: int
    max_operators: int
    created_at: datetime
    price_per_minute_toman: int = 0


class TenantDetail(TenantOut):
    balance_seconds: int = 0
    balance_toman: int = 0
    calls_total: int = 0
    users: list[UserOut] = Field(default_factory=list)
    plan_monthly_minutes: int = 0


class TopupCreate(BaseModel):
    minutes: int = Field(gt=0)
    toman: int | None = None
    note: str | None = None
    idempotency_key: str | None = None


class PlatformKpis(BaseModel):
    tenants_active: int
    calls_today: int
    calls_failed_today: int
    minutes_today: float
    queue_depth: dict[str, int]
    jobs_failed_retryable: int


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    call_id: UUID
    kind: str
    status: str
    attempt: int
    run_after: datetime
    queued_at: datetime
    started_at: datetime | None
    provider_submitted_at: datetime | None
    completed_at: datetime | None
    error_code: str | None
    error_detail: str | None


class AuditEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    actor_type: str
    actor_id: UUID | None
    tenant_id: UUID | None
    action: str
    payload: dict[str, Any]
    created_at: datetime


class NineRouterConnectionInput(BaseModel):
    ninerouter_base_url: str | None = None
    ninerouter_api_key: str | None = Field(default=None, max_length=4096)
    ninerouter_connect_timeout_seconds: int | None = Field(default=None, ge=1, le=60)
    ninerouter_read_timeout_seconds: int | None = Field(default=None, ge=10, le=3600)


class SettingsUpdate(BaseModel):
    asr_model: str | None = None
    llm_provider: Literal["local", "voicesanj"] | None = None
    llm_model: str | None = None
    chat_model: str | None = None
    prompt_version: str | None = None
    extract_prompt: str | None = Field(default=None, max_length=100_000)
    assistant_instructions: str | None = Field(default=None, max_length=100_000)
    api_key: str | None = None
    voicesanj_base_url: str | None = None
    asr_provider: Literal["local", "voicesanj", "openai_compatible"] | None = None
    asr_base_url: str | None = None
    asr_api_key: str | None = None
    audio_preprocessing_enabled: bool | None = None
    audio_denoiser_model: str | None = None
    audio_enhancement_model: str | None = None
    mono_diarization_enabled: bool | None = None
    diarization_model: str | None = Field(default=None, min_length=1, max_length=100)
    turn_min_seconds: float | None = Field(default=None, ge=0.1, le=3.0)
    turn_padding_seconds: float | None = Field(default=None, ge=0.0, le=1.0)
    turn_merge_gap_ms: int | None = Field(default=None, ge=0, le=5000)
    analysis_concurrency: int | None = Field(default=None, ge=1, le=3)
    decision_model: str | None = Field(default=None, min_length=1, max_length=80)
    decision_fallback_model: str | None = Field(default=None, min_length=1, max_length=80)
    decision_confidence_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    decision_api_key: str | None = None
    embedding_base_url: str | None = None
    embedding_api_key: str | None = None
    embedding_model: str | None = Field(default=None, min_length=1, max_length=200)
    asr_route: Literal["native", "ninerouter"] | None = None
    analysis_route: Literal["durable", "ninerouter"] | None = None
    chat_route: Literal["durable", "synchronous", "ninerouter"] | None = None
    decision_route: Literal["native", "ninerouter", "typed"] | None = None
    embedding_route: Literal["native", "ninerouter"] | None = None
    ninerouter_asr_prompt: str | None = Field(default=None, max_length=20_000)
    ninerouter_analysis_prompt: str | None = Field(default=None, max_length=20_000)
    ninerouter_chat_prompt: str | None = Field(default=None, max_length=20_000)
    ninerouter_decision_prompt: str | None = Field(default=None, max_length=20_000)
    assistant_tool_mode: Literal["auto", "native", "structured"] | None = None
    assistant_max_tool_calls: int | None = Field(default=None, ge=1, le=4)
    assistant_parallel_tools: int | None = Field(default=None, ge=1, le=2)
    assistant_enabled_tools: list[
        Literal[
            "get_current_time",
            "search_calls",
            "get_call_details",
            "search_transcripts",
            "get_call_analysis",
            "get_call_analytics",
            "get_operator_performance",
            "visualize_statistics",
        ]
    ] | None = Field(default=None, min_length=1, max_length=8)
    correction_enabled: bool | None = None
    correction_mode: Literal["text_only", "audio_only", "two_stage"] | None = None
    correction_audio_models: list[str] | None = Field(default=None, min_length=1, max_length=5)
    correction_text_models: list[str] | None = Field(default=None, min_length=1, max_length=5)
    correction_prompt: str | None = Field(default=None, min_length=20, max_length=20_000)
    correction_strictness: Literal["strict", "balanced"] | None = None
    correction_max_uncertain_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    correction_timeout_seconds: int | None = Field(default=None, ge=60, le=3600)
    correction_max_retries: int | None = Field(default=None, ge=1, le=5)
    correction_failure_policy: Literal["stop"] | None = None
    asr_ai_provider: Literal["aiservice", "ninerouter_direct"] | None = None
    analysis_provider: Literal["aiservice", "ninerouter_direct"] | None = None
    assistant_provider: Literal["aiservice", "ninerouter_direct"] | None = None
    correction_provider: Literal["aiservice", "ninerouter_direct"] | None = None
    decision_provider: Literal["aiservice", "ninerouter_direct"] | None = None
    embedding_provider: Literal["aiservice", "ninerouter_direct"] | None = None
    ninerouter_base_url: str | None = None
    ninerouter_api_key: str | None = Field(default=None, max_length=4096)
    ninerouter_connect_timeout_seconds: int | None = Field(default=None, ge=1, le=60)
    ninerouter_read_timeout_seconds: int | None = Field(default=None, ge=10, le=3600)
    ninerouter_asr_model: str | None = Field(default=None, max_length=200)
    ninerouter_analysis_model: str | None = Field(default=None, max_length=200)
    ninerouter_assistant_model: str | None = Field(default=None, max_length=200)
    ninerouter_correction_models: list[str] | None = Field(default=None, max_length=5)
    ninerouter_decision_model: str | None = Field(default=None, max_length=200)
    ninerouter_embedding_model: str | None = Field(default=None, max_length=200)
    ninerouter_direct_asr_prompt: str | None = Field(default=None, max_length=20_000)
    ninerouter_direct_analysis_prompt: str | None = Field(default=None, max_length=20_000)
    ninerouter_direct_assistant_prompt: str | None = Field(default=None, max_length=20_000)
    ninerouter_direct_correction_prompt: str | None = Field(default=None, max_length=20_000)
    ninerouter_direct_decision_prompt: str | None = Field(default=None, max_length=20_000)


class KnowledgeRetryRequest(BaseModel):
    tenant_id: UUID | None = None
    call_id: UUID | None = None
    failed_only: bool = True


class ProviderModelOut(BaseModel):
    id: str
    kind: str
    display_name: str = ""
    description: str = ""
    recommended: bool = False
    available: bool | None = None
    status: str | None = None
    language: str | None = None
    model_id: str | None = None
    architecture: str | None = None
    license: str | None = None


class PackageCreate(BaseModel):
    name: str
    minutes: int = Field(gt=0)
    price_toman: int = Field(gt=0)
    active: bool = True


class PackageUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    minutes: int | None = Field(default=None, gt=0)
    price_toman: int | None = Field(default=None, gt=0)
    active: bool | None = None


class StaffCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    role: Literal["super_admin", "support"] = "support"
    current_password: str = Field(min_length=1, max_length=128)
    totp_code: str | None = Field(default=None, pattern=r"^[0-9]{6}$")


class StaffSensitiveAction(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    totp_code: str | None = Field(default=None, pattern=r"^[0-9]{6}$")


class StaffPasswordReset(StaffSensitiveAction):
    password: str = Field(min_length=8, max_length=128)


ModuleSeverity = Literal["normal", "recommended", "critical", "security"]
ModuleChannel = Literal["stable", "beta"]
ModuleUpdateStatus = Literal["started", "succeeded", "failed", "rolled_back"]


class ModuleReleaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    product: str
    version: str
    title: str
    changelog_html: str
    severity: ModuleSeverity
    channel: ModuleChannel
    min_freepbx_major: int | None
    max_freepbx_major: int | None = None
    min_php_version: str | None = None
    min_from_version: str | None
    artifact_sha256: str
    artifact_size: int
    status: Literal["draft", "published", "revoked"]
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime
    installations: int = 0


class ModuleReleaseUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    changelog_html: str | None = Field(default=None, max_length=200_000)
    severity: ModuleSeverity | None = None
    channel: ModuleChannel | None = None
    min_freepbx_major: int | None = Field(default=None, ge=13, le=99)
    max_freepbx_major: int | None = Field(default=None, ge=13, le=99)
    min_php_version: str | None = Field(default=None, pattern=r"^\d{1,2}\.\d{1,2}(\.\d{1,3})?$")
    min_from_version: str | None = Field(default=None, max_length=32)


class ModuleZipInspection(BaseModel):
    rawname: str
    version: str
    sha256: str
    size: int
    latest_published: str | None
    already_exists: bool


class ModuleChangelogEntry(BaseModel):
    id: UUID
    version: str
    title: str
    severity: ModuleSeverity
    html: str
    published_at: datetime | None


class ModuleUpdateOffer(BaseModel):
    id: UUID
    version: str
    severity: ModuleSeverity
    title: str
    size: int
    sha256: str
    signature: str
    published_at: datetime | None
    # Signed manifest (new in module 1.4.0): binds version, digest, size, channel and an expiry.
    manifest: str | None = None
    manifest_signature: str | None = None


class ModuleUpdateCheckOut(BaseModel):
    update_available: bool
    # True when the version the host runs was revoked (for example a bad release): update soon.
    current_revoked: bool = False
    current: str
    latest: ModuleUpdateOffer | None
    changelog: list[ModuleChangelogEntry]
    server_time: datetime


class ModuleUpdateReportIn(BaseModel):
    host_uuid: str = Field(min_length=8, max_length=64)
    release_id: UUID | None = None
    from_version: str | None = Field(default=None, max_length=32)
    to_version: str = Field(min_length=1, max_length=32)
    status: ModuleUpdateStatus
    message: str | None = Field(default=None, max_length=4000)


class ModuleInstallationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    tenant_name: str | None = None
    host_uuid: str
    hostname: str | None
    freepbx_version: str | None
    php_version: str | None
    module_version: str
    service_status: str | None
    last_seen_at: datetime
    last_update_status: ModuleUpdateStatus | None
    last_update_error: str | None
    last_update_at: datetime | None
    update_available: bool = False
    latest_version: str | None = None


# --- help center -------------------------------------------------------------

HelpKind = Literal["article", "error", "faq"]
HelpStatus = Literal["draft", "published"]
HelpSeverity = Literal["info", "warning", "error", "critical"]
HelpSource = Literal["module", "api", "worker"]


class HelpCategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    slug: str
    title: str
    description: str
    position: int
    article_count: int = 0


class HelpCategoryIn(BaseModel):
    slug: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    position: int = Field(default=0, ge=0, le=10000)


class HelpArticleSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    slug: str
    title: str
    summary: str
    kind: HelpKind
    category_id: UUID | None
    status: HelpStatus
    position: int
    published_at: datetime | None
    updated_at: datetime


class HelpArticleOut(HelpArticleSummary):
    body_html: str
    error_codes: list[str] = []


class HelpArticleIn(BaseModel):
    slug: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=250)
    summary: str = Field(default="", max_length=1000)
    body_html: str = Field(default="", max_length=400_000)
    kind: HelpKind = "article"
    category_id: UUID | None = None
    position: int = Field(default=0, ge=0, le=10000)
    error_codes: list[str] = Field(default_factory=list, max_length=40)


class HelpArticleUpdate(BaseModel):
    slug: str | None = Field(default=None, min_length=1, max_length=120)
    title: str | None = Field(default=None, min_length=1, max_length=250)
    summary: str | None = Field(default=None, max_length=1000)
    body_html: str | None = Field(default=None, max_length=400_000)
    kind: HelpKind | None = None
    category_id: UUID | None = None
    clear_category: bool = False
    position: int | None = Field(default=None, ge=0, le=10000)
    error_codes: list[str] | None = Field(default=None, max_length=40)


class HelpArticleList(BaseModel):
    items: list[HelpArticleSummary]
    total: int


class HelpErrorCodeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    source: HelpSource
    severity: HelpSeverity
    title: str
    quick_action: str
    article_slug: str | None = None
    article_title: str | None = None
    article_published: bool = False


class HelpErrorCodeIn(BaseModel):
    source: HelpSource = "module"
    severity: HelpSeverity = "error"
    title: str = Field(default="", max_length=250)
    quick_action: str = Field(default="", max_length=2000)
    article_id: UUID | None = None


class HelpMediaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: Literal["image", "video"]
    filename: str
    content_type: str
    size_bytes: int
    alt: str
    created_at: datetime
    url: str = ""


class ModuleDiagnosticCheck(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    status: Literal["ok", "warn", "fail"]
    code: str = Field(default="", max_length=40)
    detail: str = Field(default="", max_length=300)


class ModuleDiagnosticIn(BaseModel):
    host_uuid: str = Field(min_length=8, max_length=64)
    module_version: str = Field(pattern=r"^\d{1,4}\.\d{1,5}\.\d{1,6}$")
    ok: bool
    failed_checks: int = Field(default=0, ge=0, le=1000)
    asterisk_version: str | None = Field(default=None, max_length=64)
    os_name: str | None = Field(default=None, max_length=80)
    checks: list[ModuleDiagnosticCheck] = Field(default_factory=list, max_length=80)
    recent_codes: dict[str, int] = Field(default_factory=dict, max_length=40)
    queue: dict[str, int] = Field(default_factory=dict, max_length=20)


class ModuleDiagnosticOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    module_version: str
    ok: bool
    failed_checks: int
    report: dict[str, Any]
    created_at: datetime


class ContactIn(BaseModel):
    name: str = Field(max_length=1000)
    phone_number: str = Field(max_length=100)
    company: str | None = Field(default=None, max_length=1000)
    email: str | None = Field(default=None, max_length=1000)
    province: str | None = Field(default=None, max_length=200)
    city: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=10000)


class ContactUpdate(BaseModel):
    """Only the fields present in the request change; an explicit null clears an optional one."""

    name: str | None = Field(default=None, max_length=1000)
    phone_number: str | None = Field(default=None, max_length=100)
    company: str | None = Field(default=None, max_length=1000)
    email: str | None = Field(default=None, max_length=1000)
    province: str | None = Field(default=None, max_length=200)
    city: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=10000)


class ContactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    phone_number: str
    company: str | None = None
    email: str | None = None
    province: str | None = None
    city: str | None = None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime


class ExtensionSyncItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    extension: str = Field(min_length=1, max_length=20)
    name: str | None = Field(default=None, max_length=200)


class ExtensionSyncIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    extensions: list[ExtensionSyncItem] = Field(max_length=5000)


class ExtensionSyncOut(BaseModel):
    created: int
    updated: int
    deactivated: int
    total: int


class ExtensionOut(BaseModel):
    id: UUID
    extension: str
    pbx_name: str | None = None
    active: bool
    contact_id: UUID | None = None
    contact_name: str | None = None
    user_id: UUID | None = None
    user_name: str | None = None
    synced_at: datetime


class ExtensionUpdate(BaseModel):
    """Omitted field = unchanged; explicit null = unlink."""

    contact_id: UUID | None = None
    user_id: UUID | None = None


class ContactPage(BaseModel):
    items: list[ContactOut]
    total: int
    page: int
    page_size: int
    pages: int


class ContactImportError(BaseModel):
    row: int
    message: str


class ContactImportReport(BaseModel):
    dry_run: bool
    mode: Literal["skip", "update"]
    total_rows: int
    created: int
    updated: int
    skipped: int
    error_count: int
    errors: list[ContactImportError]
