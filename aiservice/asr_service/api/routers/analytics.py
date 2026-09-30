"""Usage history and aggregate statistics endpoints."""

import json
import os
import threading
import time

from fastapi import APIRouter, Depends, HTTPException, Query

from asr_service.infrastructure import storage
from asr_service.infrastructure.storage import row, rows
from asr_service.services.system_monitor import snapshot
from asr_service.services.resources import scheduler_state
from asr_service.services.task_queue import cancel_all_active, serialize_run

from ..dependencies import authorize_admin
from ..openapi import documented_responses
from ..schemas.common import ErrorResponse
from ..schemas.responses import (
    StatsResponse, SystemMetricsResponse, UsageDetailResponse, UsageFiltersResponse,
    UsagePageResponse,
)

router = APIRouter(
    prefix="/api", tags=["Usage analytics"], dependencies=[Depends(authorize_admin)]
)

_STATS_CACHE_SECONDS = 5.0
_stats_cache_lock = threading.Lock()
_stats_cache_key: str | None = None
_stats_cache_expires_at = 0.0
_stats_cache_value: dict | None = None


@router.get(
    "/stats",
    response_model=StatsResponse,
    summary="Get aggregate usage statistics",
    description="Returns lifetime totals, a fourteen-day request series, and performance aggregates grouped by model.",
    responses=documented_responses(),
)
def stats():
    """Aggregate usage counts, audio duration, and model performance."""

    global _stats_cache_key, _stats_cache_expires_at, _stats_cache_value
    cache_key = str(storage.DB_PATH)
    now = time.monotonic()
    with _stats_cache_lock:
        if (
            _stats_cache_key == cache_key
            and _stats_cache_value is not None
            and now < _stats_cache_expires_at
        ):
            return _stats_cache_value

    result = row(
        "SELECT count(*) total,coalesce(sum(status='success'),0) success,coalesce(sum(status='failed'),0) failed,coalesce(sum(status='partial_success'),0) partial,coalesce(sum(duration_seconds),0) audio_seconds FROM usage"
    )
    result["daily"] = rows(
        "SELECT substr(created_at,1,10) day,count(*) count FROM usage WHERE created_at>=datetime('now','-14 days') GROUP BY day ORDER BY day"
    )
    result["per_model"] = rows(
        """WITH executions AS (
        SELECT model_id,status,processing_seconds,duration_seconds FROM task_runs
        UNION ALL
        SELECT u.model_id,CASE WHEN u.status='success' THEN 'succeeded' ELSE 'failed' END,u.processing_seconds,u.duration_seconds
        FROM usage u LEFT JOIN task_runs r ON r.usage_id=u.id
        WHERE u.model_id IS NOT NULL AND r.id IS NULL
        )
        SELECT model_id,count(*) total,coalesce(sum(status='succeeded'),0) success,coalesce(sum(status='failed'),0) failed,
        round(avg(CASE WHEN processing_seconds IS NOT NULL THEN processing_seconds END),2) avg_processing_seconds,
        round(avg(CASE WHEN duration_seconds>0 AND processing_seconds IS NOT NULL THEN processing_seconds/duration_seconds END),2) avg_realtime_factor,
        round(sum(coalesce(duration_seconds,0))/60.0,1) audio_minutes
        FROM executions GROUP BY model_id ORDER BY total DESC"""
    )
    with _stats_cache_lock:
        _stats_cache_key = cache_key
        _stats_cache_value = result
        _stats_cache_expires_at = time.monotonic() + _STATS_CACHE_SECONDS
    return result


@router.get(
    "/system-metrics",
    response_model=SystemMetricsResponse,
    summary="Get current system resource utilization",
    description="Returns CPU, memory, swap, storage, disk I/O, network, uptime, load average, and the busiest processes visible to the service.",
    responses=documented_responses(),
)
def system_metrics():
    """Return a non-blocking resource snapshot for the administration overview."""

    result = snapshot()
    result["scheduler"] = scheduler_state()
    return result


@router.post(
    "/inference/interrupt-all",
    summary="Immediately interrupt all inference",
    description="Cancels every queued and running asynchronous task, then terminates this service process. Docker restarts the container, which immediately releases native ASR/LLM CPU and RAM resources.",
)
def interrupt_all_inference():
    """Emergency stop for native inference which cannot be stopped in-process."""

    interrupted = cancel_all_active()

    def terminate_after_response():
        # Let the HTTP response and SQLite WAL commit leave the process first.
        time.sleep(0.25)
        os._exit(0)

    threading.Thread(target=terminate_after_response, daemon=True).start()
    return {"interrupted": len(interrupted), "restarting": True}


@router.get(
    "/usage",
    response_model=UsagePageResponse,
    summary="List usage records",
    description="Returns the newest persisted request records with bounded pagination. Sensitive request bodies and API keys are never included.",
    responses=documented_responses(include_validation=True),
)
def usage(
    page: int = Query(default=1, description="One-based page number."),
    page_size: int = Query(
        default=20,
        description="Requested page size; values are clamped to 1 through 100.",
    ),
    active: bool = Query(
        default=False,
        description="When true, return only queued and processing requests, oldest first.",
    ),
    model: str | None = Query(default=None, description="Only requests that ran this model."),
    kind: str | None = Query(default=None, description="Request/conversion kind, such as asr or text."),
    operation: str | None = Query(default=None, description="Text conversion operation, such as correction or minutes."),
    response_format: str | None = Query(default=None, description="Requested output format."),
    status: str | None = Query(default=None, description="Persisted request status."),
    client_ip: str | None = Query(default=None, description="Exact client IP address."),
    created_from: str | None = Query(default=None, description="Inclusive ISO date/time lower bound."),
    created_to: str | None = Query(default=None, description="Inclusive ISO date/time upper bound."),
):
    """Return a reverse-chronological page of usage records."""

    # Route functions are also used directly by the lightweight unit tests. FastAPI
    # normally resolves omitted Query defaults to None before invoking this code.
    model, kind, operation, response_format, status, client_ip, created_from, created_to = (
        value if isinstance(value, str) else None
        for value in (model, kind, operation, response_format, status, client_ip, created_from, created_to)
    )
    page = max(page, 1)
    page_size = max(1, min(page_size, 100))
    conditions, args = [], []
    source = "FROM usage u LEFT JOIN tasks t ON t.usage_id=u.id"
    if active:
        source = """FROM (
            SELECT usage_id FROM tasks WHERE status IN ('queued','retrying','running')
            UNION
            SELECT u.id FROM usage u
            WHERE u.status IN ('queued','processing')
            AND NOT EXISTS(SELECT 1 FROM tasks legacy_task WHERE legacy_task.usage_id=u.id)
        ) active_usage
        JOIN usage u ON u.id=active_usage.usage_id
        LEFT JOIN tasks t ON t.usage_id=u.id"""
    if model:
        conditions.append("(u.model_id=? OR EXISTS(SELECT 1 FROM task_runs filter_runs WHERE filter_runs.usage_id=u.id AND filter_runs.model_id=?))")
        args.extend((model, model))
    if kind:
        conditions.append("t.kind=?")
        args.append(kind)
    if operation:
        conditions.append("json_extract(t.input_json, '$.operation')=?")
        args.append(operation)
    if response_format:
        conditions.append("u.response_format=?")
        args.append(response_format)
    if status:
        conditions.append("(" + ("CASE WHEN t.status IN ('queued','retrying') THEN 'queued' WHEN t.status='running' THEN 'processing' ELSE u.status END" if active else "u.status") + ")=?")
        args.append(status)
    if client_ip:
        conditions.append("u.client_ip=?")
        args.append(client_ip)
    if created_from:
        conditions.append("u.created_at>=?")
        args.append(created_from)
    if created_to:
        conditions.append("u.created_at<=?")
        args.append(created_to)
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    order = "u.id ASC" if active else "u.id DESC"
    status_column = (
        "CASE WHEN t.status IN ('queued','retrying') THEN 'queued' "
        "WHEN t.status='running' THEN 'processing' ELSE u.status END"
        if active else "u.status"
    )
    started_column = (
        "CASE WHEN t.status='running' THEN (SELECT r.attempt_started_at FROM task_runs r "
        "WHERE r.task_id=t.task_id AND r.status='processing' ORDER BY r.position LIMIT 1) END"
        if active else "t.started_at"
    )
    processing_column = (
        "coalesce((SELECT sum(r.processing_seconds) FROM task_runs r WHERE r.task_id=t.task_id),0)"
        if active else "u.processing_seconds"
    )
    items = rows(
        "SELECT u.id,u.created_at,u.finished_at,u.model_id,t.kind,json_extract(t.input_json, '$.operation') operation,u.filename," + status_column + " status,"
        "u.duration_seconds," + processing_column + " processing_seconds,u.audio_bytes,u.response_format,u.error,"
        "u.execution_log,u.client_ip,t.task_id," + started_column + " started_at "
        + source + where + " ORDER BY " + order + " LIMIT ? OFFSET ?",
        (*args, page_size, (page - 1) * page_size),
    )
    runs_by_usage = {item["id"]: [] for item in items}
    if items:
        placeholders = ",".join("?" for _ in items)
        for run in rows(
            "SELECT usage_id,model_id,status FROM task_runs WHERE usage_id IN ("
            + placeholders
            + ") ORDER BY usage_id,position",
            tuple(runs_by_usage),
        ):
            runs_by_usage[run["usage_id"]].append(run)
    for item in items:
        runs = runs_by_usage[item["id"]]
        item["models"] = [run["model_id"] for run in runs] or (
            [item["model_id"]] if item.get("model_id") else []
        )
        item["successful_models"] = sum(run["status"] == "succeeded" for run in runs)
        item["failed_models"] = sum(
            run["status"] in {"failed", "cancelled"} for run in runs
        )
        item["completed_models"] = sum(
            run["status"] in {"succeeded", "failed", "cancelled", "skipped"}
            for run in runs
        )
        item["total_models"] = len(item["models"])
        if not runs and item.get("model_id"):
            item["successful_models"] = int(item["status"] == "success")
            item["failed_models"] = int(item["status"] == "failed")
            item["completed_models"] = int(item["status"] in {"success", "failed"})
    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": row(
            "SELECT count(*) n " + source + where,
            tuple(args),
        )["n"],
    }


@router.get(
    "/usage/filters",
    response_model=UsageFiltersResponse,
    summary="List available usage-history filters",
    description="Returns distinct non-sensitive values already persisted in usage history.",
    responses=documented_responses(),
)
def usage_filters():
    """Return filter choices based on actual persisted history, not a hard-coded list."""

    def values(sql):
        return [item["value"] for item in rows(sql) if item.get("value") not in (None, "")]

    return {
        "models": values("SELECT model_id value FROM usage WHERE model_id IS NOT NULL UNION SELECT model_id FROM task_runs WHERE model_id IS NOT NULL ORDER BY value"),
        "kinds": values("SELECT DISTINCT kind value FROM tasks WHERE kind IS NOT NULL ORDER BY value"),
        "operations": values("SELECT DISTINCT json_extract(input_json, '$.operation') value FROM tasks WHERE json_extract(input_json, '$.operation') IS NOT NULL ORDER BY value"),
        "response_formats": values("SELECT DISTINCT response_format value FROM usage WHERE response_format IS NOT NULL ORDER BY value"),
        "statuses": values("SELECT DISTINCT status value FROM usage WHERE status IS NOT NULL ORDER BY value"),
        "client_ips": values("SELECT DISTINCT client_ip value FROM usage WHERE client_ip IS NOT NULL ORDER BY value"),
    }


@router.get(
    "/usage/{usage_id}",
    response_model=UsageDetailResponse,
    summary="Get usage execution details",
    description="Returns ordered per-model runs and append-only execution events for one persisted request.",
    responses=documented_responses(
        **{"404": {"model": ErrorResponse, "description": "Usage record not found."}}
    ),
)
def usage_detail(usage_id: int):
    item = row(
        """SELECT u.id,u.model_id,u.status,u.response_format,u.content_type,u.result_json,t.task_id,t.kind
        FROM usage u LEFT JOIN tasks t ON t.usage_id=u.id WHERE u.id=?""",
        (usage_id,),
    )
    if not item:
        raise HTTPException(404, "Usage record not found")
    events = rows(
        "SELECT created_at,level,event_type,message FROM task_events WHERE usage_id=? ORDER BY id",
        (usage_id,),
    )
    runs = rows(
        """SELECT id,position,model_id,status,attempts,started_at,finished_at,
        duration_seconds,processing_seconds,result_json,error
        FROM task_runs WHERE usage_id=? ORDER BY position""",
        (usage_id,),
    )
    for run in runs:
        serialized = serialize_run(run, item.get("response_format") or "verbose_json")
        run["position"] = serialized["position"]
        run["content_type"] = serialized["content_type"]
        run["result"] = None if item.get("kind") == "chat_async" else serialized["result"]
        run.pop("result_json", None)
        run["events"] = rows(
            "SELECT created_at,level,event_type,message FROM task_run_events WHERE run_id=? ORDER BY id",
            (run["id"],),
        )
    raw_result = item.pop("result_json", None)
    if item.pop("kind", None) == "chat_async":
        item["result"] = None
    elif raw_result:
        try:
            item["result"] = json.loads(raw_result)
        except (TypeError, json.JSONDecodeError):
            item["result"] = raw_result
    else:
        item["result"] = None
    return {**item, "events": events, "runs": runs}
