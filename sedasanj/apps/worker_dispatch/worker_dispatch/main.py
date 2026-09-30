from __future__ import annotations

import time
from typing import Any

from arq import cron
from arq.connections import RedisSettings

from app.config import get_settings
from app.db import dispose_engine
from app.logging import configure_logging
from app.metrics import start_metrics_server
from app.services import outbox, queue
from app.services.maintenance import refresh_failure_gauge, refresh_queue_depth


async def dispatch_tick(ctx: dict[str, Any]) -> str:
    now = time.monotonic()
    interval = get_settings().outbox_dispatch_interval_seconds
    if now - float(ctx.get("last_dispatch", 0.0)) < interval:
        return "dispatch_skipped"
    delivered = await outbox.dispatch_pending()
    ctx["last_dispatch"] = now
    if now - float(ctx.get("last_metrics", 0.0)) >= 15.0:
        await refresh_queue_depth()
        await refresh_failure_gauge()
        ctx["last_metrics"] = now
    return f"dispatched:{delivered}"


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    configure_logging("worker-dispatch", settings.log_level)
    start_metrics_server(settings)
    ctx["last_dispatch"] = 0.0
    ctx["last_metrics"] = 0.0
    await dispatch_tick(ctx)


async def shutdown(ctx: dict[str, Any]) -> None:
    await queue.get_queue().close()
    await dispose_engine()


class WorkerSettings:
    functions = [dispatch_tick]
    cron_jobs = [cron(dispatch_tick, second=set(range(60)))]
    queue_name = "q:dispatch"
    on_startup = startup
    on_shutdown = shutdown
    max_jobs = 2
    job_timeout = 30
    keep_result = 60
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
