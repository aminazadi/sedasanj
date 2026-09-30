"""Response models used to document every successful and error status code."""

from typing import Any, Literal

from pydantic import Field

from .common import ApiSchema, TaskStatus


class QueueCapacity(ApiSchema):
    """Current persistent task-queue utilization."""

    active: int = Field(
        ge=0, description="Number of queued, retrying, or running tasks."
    )
    capacity: int = Field(
        ge=1, description="Maximum tasks accepted before backpressure is applied."
    )


class DecisionAnswerResponse(ApiSchema):
    """One calibrated, non-generative answer to a typed decision question."""

    type: Literal["choice", "multi_label", "score", "noul"]
    answer: Any | None = None
    probabilities: dict[str, float] = Field(default_factory=dict)
    confidence: float = Field(ge=0, le=1)
    margin: float = Field(ge=0, le=1)
    abstained: bool


class DecisionResultResponse(ApiSchema):
    """Versioned normalized response returned by a successful decision task."""

    version: Literal["v1"] = "v1"
    model: str
    engine: Literal["gliner2_5_multi_decide", "laya_multilingual"]
    answers: dict[str, DecisionAnswerResponse]
    capabilities: list[str]
    latency_ms: float = Field(ge=0)


class HealthResponse(ApiSchema):
    """Service liveness and model readiness information."""

    status: Literal["ok"]
    ready: bool = Field(description="True when at least one model is installed.")
    installed_models: list[str] = Field(description="Identifiers of installed models.")
    tasks: QueueCapacity


class ModelFileResponse(ApiSchema):
    """One artifact required by a downloadable model."""

    filename: str
    url: str
    expected_size: int | None = None
    size_is_estimate: bool = False
    sha256: str | None = None


class ModelResponse(ApiSchema):
    """Catalog metadata combined with the local installation state."""

    id: str
    kind: str
    display_name: str
    description: str
    repository_url: str
    architecture: str | None = None
    recommended: bool = False
    files: list[ModelFileResponse]
    revision: str | None = None
    license: str | None = None
    preparation: str | None = None
    language: str | None = None
    task: str | None = None
    decoding: dict[str, Any] = Field(default_factory=dict)
    engine: str | None = None
    source_type: str | None = None
    source: dict[str, Any] = Field(default_factory=dict)
    model_id: str
    status: str
    received_bytes: int = 0
    total_bytes: int = 0
    speed_bps: float = 0
    error: str | None = None
    installed_at: str | None = None
    updated_at: str | None = None
    job_id: str | None = None
    available: bool
    custom: bool = False


class ModelStateResponse(ApiSchema):
    """Download and installation state for a model."""

    model_id: str
    status: str = Field(description="Current installation lifecycle state.")
    received_bytes: int = 0
    total_bytes: int = 0
    speed_bps: float = 0
    error: str | None = None
    installed_at: str | None = None
    updated_at: str | None = None
    job_id: str | None = None


class ProxyTestResponse(ApiSchema):
    """Most recent connectivity test, with credentials redacted."""

    state: Literal["disabled", "connected", "error"]
    message: str
    checked_at: str
    target: str
    remote_dns: bool
    latency_ms: int | None = None
    http_status: int | None = None
    final_url: str | None = None


class ProxyConfigResponse(ApiSchema):
    """Public proxy configuration safe to return to API clients."""

    enabled: bool
    host: str
    port: int
    username: str
    has_password: bool
    scheme: str
    uri: str = Field(description="Proxy URI with its password redacted.")
    last_test: ProxyTestResponse | None = None


class DailyUsageResponse(ApiSchema):
    day: str
    count: int


class PerModelStatsResponse(ApiSchema):
    model_id: str
    total: int
    success: int
    failed: int
    avg_processing_seconds: float | None = None
    avg_realtime_factor: float | None = None
    audio_minutes: float | None = None


class StatsResponse(ApiSchema):
    """Aggregate service usage statistics."""

    total: int
    success: int
    failed: int
    partial: int = 0
    audio_seconds: float
    daily: list[DailyUsageResponse]
    per_model: list[PerModelStatsResponse]


class CpuMetricsResponse(ApiSchema):
    percent: float
    cores: int
    per_core: list[float]


class MemoryMetricsResponse(ApiSchema):
    total: int
    used: int
    available: int
    free: int = 0
    cached: int = 0
    percent: float
    swap_total: int
    swap_used: int
    swap_percent: float


class DiskMetricsResponse(ApiSchema):
    scope: Literal["host", "container", "requested"] = "container"
    path: str
    device: str | None = None
    total: int
    used: int
    free: int
    percent: float
    read_bytes_per_second: int
    write_bytes_per_second: int


class NetworkInterfaceResponse(ApiSchema):
    name: str
    received: int
    sent: int


class NetworkMetricsResponse(ApiSchema):
    interface: str | None = None
    received: int
    sent: int
    receive_bytes_per_second: int
    send_bytes_per_second: int
    interfaces: list[NetworkInterfaceResponse]


class ProcessMetricsResponse(ApiSchema):
    pid: int
    name: str
    cpu_percent: float
    memory_bytes: int


class ContainerMetricsResponse(ApiSchema):
    hostname: str
    cpu_percent: float
    cpu_capacity: int
    memory: MemoryMetricsResponse
    network: NetworkMetricsResponse
    process_count: int


class SchedulerMetricsResponse(ApiSchema):
    mode: str
    active: int
    target: int
    hard_limit: int
    workers: int
    llm_max_concurrent: int
    asr_threads_per_job: int
    llm_threads_per_job: int
    cpu_ema_percent: float
    memory_ema_percent: float
    cpu_stop_percent: float
    memory_stop_percent: float


class SystemMetricsResponse(ApiSchema):
    """Current VPS/container resource utilization."""

    scope: Literal["host", "container"]
    hostname: str
    platform: str
    uptime_seconds: float
    load_average: list[float]
    cpu: CpuMetricsResponse
    memory: MemoryMetricsResponse
    disk: DiskMetricsResponse
    network: NetworkMetricsResponse
    process_count: int
    processes: list[ProcessMetricsResponse]
    container: ContainerMetricsResponse
    scheduler: SchedulerMetricsResponse
    sampled_at: float


class UsageItemResponse(ApiSchema):
    id: int
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    model_id: str
    kind: str | None = None
    operation: str | None = None
    filename: str | None = None
    status: str
    duration_seconds: float | None = None
    processing_seconds: float | None = None
    audio_bytes: int | None = None
    response_format: str | None = None
    error: str | None = None
    execution_log: str | None = None
    client_ip: str | None = None
    task_id: str | None = None
    models: list[str] = Field(default_factory=list)
    successful_models: int = 0
    failed_models: int = 0
    completed_models: int = 0
    total_models: int = 0


class UsagePageResponse(ApiSchema):
    items: list[UsageItemResponse]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    total: int = Field(ge=0)


class UsageFiltersResponse(ApiSchema):
    """Distinct, non-sensitive values available for narrowing usage history."""

    models: list[str] = Field(default_factory=list)
    kinds: list[str] = Field(default_factory=list)
    operations: list[str] = Field(default_factory=list)
    response_formats: list[str] = Field(default_factory=list)
    statuses: list[str] = Field(default_factory=list)
    client_ips: list[str] = Field(default_factory=list)


class ExecutionEventResponse(ApiSchema):
    created_at: str
    level: str
    event_type: str
    message: str


class UsageModelRunResponse(ApiSchema):
    id: int
    position: int
    model_id: str
    status: str
    attempts: int
    started_at: str | None = None
    finished_at: str | None = None
    duration_seconds: float | None = None
    processing_seconds: float | None = None
    content_type: str = "application/json"
    result: Any | None = None
    error: str | None = None
    events: list[ExecutionEventResponse] = Field(default_factory=list)


class UsageDetailResponse(ApiSchema):
    id: int
    task_id: str | None = None
    model_id: str | None = None
    status: str
    response_format: str | None = None
    content_type: str | None = None
    result: Any | None = None
    events: list[ExecutionEventResponse] = Field(default_factory=list)
    runs: list[UsageModelRunResponse] = Field(default_factory=list)


class RequestFailureItemResponse(ApiSchema):
    id: int
    created_at: str
    status_code: int | None = None
    phase: str
    reason: str
    detail: str | None = None
    client_ip: str | None = None
    origin: str | None = None
    method: str
    path: str
    query_string: str | None = None
    x_forwarded_for: str | None = None
    x_real_ip: str | None = None
    forwarded: str | None = None
    user_agent: str | None = None
    requested_method: str | None = None
    requested_headers: str | None = None
    task_id: str | None = None
    usage_id: int | None = None


class RequestFailurePageResponse(ApiSchema):
    items: list[RequestFailureItemResponse]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=200)
    total: int = Field(ge=0)


class TaskResponse(ApiSchema):
    """Public state and resource links for an asynchronous task."""

    task_id: str
    kind: Literal["asr", "text", "chat", "chat_async", "decision"]
    status: TaskStatus
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    updated_at: str
    model_id: str
    filename: str | None = None
    response_format: str
    attempts: int
    max_attempts: int
    duration_seconds: float | None = None
    processing_seconds: float | None = None
    error: str | None = None
    error_code: str | None = None
    status_url: str
    result_url: str | None = None
    queue_position: int | None = Field(default=None, ge=1)
    models: list[str] = Field(default_factory=list)
    current_model: str | None = None
    completed_models: int = 0
    total_models: int = 0


class ChatCompletionResultResponse(ApiSchema):
    """Complete OpenAI-compatible model response for a succeeded chat task."""

    id: str
    object: Literal["chat.completion"]
    created: int
    model: str
    choices: list[dict[str, Any]]
    usage: dict[str, Any] | None = None


class TextCorrectionResultResponse(ApiSchema):
    """Completed transcript-correction result."""

    model: str
    operation: Literal["correction"]
    corrected_text: str
    uncertain_items: list[str]


class MeetingMinutesResultResponse(ApiSchema):
    """Completed meeting-minutes result."""

    model: str
    operation: Literal["minutes"]
    minutes: str
    style: Literal["formal", "semi_formal", "action"]


class SegmentResponse(ApiSchema):
    """Timestamped transcript segment."""

    start: float
    end: float
    text: str


class TranscriptionResponse(ApiSchema):
    """Compact JSON transcription result."""

    text: str


class VerboseTranscriptionResponse(TranscriptionResponse):
    """Detailed JSON transcription result including timing metadata."""

    language: str
    duration: float
    duration_after_vad: float
    model: str
    segments: list[SegmentResponse]


class ModelRunResultResponse(ApiSchema):
    position: int
    model: str
    status: str
    attempts: int
    started_at: str | None = None
    finished_at: str | None = None
    duration_seconds: float | None = None
    processing_seconds: float | None = None
    content_type: str
    result: Any | None = None
    error: str | None = None


class MultiModelResultResponse(ApiSchema):
    task_id: str
    status: Literal["succeeded", "partially_succeeded", "failed", "cancelled"]
    results: list[ModelRunResultResponse]
