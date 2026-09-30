import logging

from prometheus_client import Counter, Gauge, Histogram, start_http_server

from app.config import Settings

logger = logging.getLogger(__name__)

ingest_total = Counter("cbi_ingest_total", "Accepted ingest uploads", ["tenant", "result"])
credit_rejects_total = Counter(
    "cbi_credit_rejects_total", "Ingests rejected for credit", ["tenant"]
)
queue_depth = Gauge("cbi_queue_depth", "Pending jobs per queue", ["queue"])
job_wait_seconds = Histogram("cbi_job_wait_seconds", "Time from enqueue to claim", ["kind"])
outbox_dispatch_seconds = Histogram(
    "cbi_outbox_dispatch_seconds", "Time from database commit intent to Redis dispatch"
)
outbox_pending = Gauge("cbi_outbox_pending", "Undispatched durable queue messages")
outbox_oldest_seconds = Gauge(
    "cbi_outbox_oldest_seconds", "Age of the oldest undispatched durable message"
)
oldest_job_seconds = Gauge(
    "cbi_oldest_job_seconds", "Age of the oldest queued job", ["kind"]
)
llm_submit_seconds = Histogram(
    "cbi_llm_submit_seconds", "Time from LLM job creation to provider submission"
)
llm_provider_wait_seconds = Histogram(
    "cbi_llm_provider_wait_seconds", "Time spent waiting for the provider task"
)
provider_tasks = Gauge("cbi_provider_tasks", "Provider analysis steps", ["status"])
asr_seconds_processed = Counter("cbi_asr_seconds_processed", "Audio seconds transcribed")
llm_tokens_per_second = Histogram("cbi_llm_tokens_per_second", "Observed llama-server throughput")
llm_json_failures_total = Counter(
    "cbi_llm_json_failures_total", "LLM outputs that failed schema validation", ["stage"]
)
webhook_responses_total = Counter(
    "cbi_webhook_responses_total", "Webhook delivery outcomes", ["status"]
)
jobs_failed_retryable = Gauge(
    "cbi_jobs_failed_retryable", "Jobs waiting for a retry after a failure"
)
http_requests_total = Counter(
    "cbi_http_requests_total", "HTTP requests", ["method", "path", "status"]
)
http_request_seconds = Histogram("cbi_http_request_seconds", "HTTP latency", ["method", "path"])


def start_metrics_server(settings: Settings) -> None:
    """§14: workers have no HTTP surface, so they expose their own scrape endpoint."""
    if settings.worker_metrics_port <= 0:
        return
    try:
        start_http_server(settings.worker_metrics_port)
    except OSError as exc:
        logger.warning("could not start worker metrics server: %r", exc)
