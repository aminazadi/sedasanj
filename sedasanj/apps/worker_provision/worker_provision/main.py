from __future__ import annotations

import logging
from typing import Any

from arq import cron
from arq.connections import RedisSettings

from app.config import get_settings
from app.db import dispose_engine
from app.logging import configure_logging
from app.metrics import start_metrics_server
from app.services.identity_projection import dispatch_next as dispatch_identity_projection
from app.services.knowledge import backfill_graph_next, backfill_next
from app.services.org_knowledge import backfill_org_next
from app.services.queue_serialization import job_deserializer, job_serializer
from app.services.tenant_provisioning import (
    run_next_fleet_migration,
    run_next_migration,
    sync_global_references,
)

logger = logging.getLogger(__name__)


async def provision_tick(ctx: dict[str, Any]) -> str:
    if not get_settings().tenant_databases_enabled:
        return "disabled"
    try:
        result = await run_next_migration()
        if result == "idle":
            return await run_next_fleet_migration()
        return result
    except Exception:
        logger.exception("tenant database provisioning failed")
        return "failed"


async def identity_projection_tick(ctx: dict[str, Any]) -> str:
    if not get_settings().tenant_databases_enabled:
        return "disabled"
    try:
        return await dispatch_identity_projection()
    except Exception:
        logger.exception("identity projection failed")
        return "failed"


async def knowledge_backfill_tick(ctx: dict[str, Any]) -> str:
    try:
        # Vectors come before the graph: a permanently failing graph row must never starve
        # the vector index the assistant retrieves from.
        for step in (backfill_next, backfill_org_next, backfill_graph_next):
            result = await step()
            if result != "idle":
                return result
        return "idle"
    except Exception:
        logger.exception("knowledge backfill failed")
        return "failed"


async def global_reference_tick(ctx: dict[str, Any]) -> str:
    if not get_settings().tenant_databases_enabled:
        return "disabled"
    try:
        return await sync_global_references()
    except Exception:
        logger.exception("global tenant reference synchronization failed")
        return "failed"


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    configure_logging("worker-provision", settings.log_level)
    start_metrics_server(settings)
    await provision_tick(ctx)


async def shutdown(ctx: dict[str, Any]) -> None:
    await dispose_engine()


class WorkerSettings:
    job_serializer = job_serializer
    job_deserializer = job_deserializer
    functions = [
        provision_tick,
        identity_projection_tick,
        knowledge_backfill_tick,
        global_reference_tick,
    ]
    cron_jobs = [
        cron(provision_tick, second={0, 15, 30, 45}),
        cron(identity_projection_tick, second={5, 20, 35, 50}),
        cron(knowledge_backfill_tick, second={10, 25, 40, 55}),
        cron(global_reference_tick, second={12, 42}),
    ]
    queue_name = "q:provision"
    on_startup = startup
    on_shutdown = shutdown
    max_jobs = 1
    job_timeout = 7200
    keep_result = 300
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
