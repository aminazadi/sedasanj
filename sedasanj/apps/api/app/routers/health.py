from __future__ import annotations

import asyncio
from hmac import compare_digest
from typing import Any

import httpx
from fastapi import APIRouter, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from redis.asyncio import Redis
from sqlalchemy import text

from app.config import get_settings, normalize_api_key
from app.db import get_sessionmaker
from app.errors import ApiError
from app.services.platform import resolve_provider_settings
from app.services.storage import get_storage

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


async def _check_postgres() -> bool:
    async with get_sessionmaker()() as session:
        await session.execute(text("SELECT 1"))
    return True


async def _check_redis() -> bool:
    settings = get_settings()
    if settings.queue_backend == "memory":
        return True
    client = Redis.from_url(settings.redis_url)
    try:
        return bool(await client.ping())
    finally:
        await client.aclose()


async def _check_storage() -> bool:
    return await get_storage().ping()


async def _check_llm() -> bool:
    settings = get_settings()
    if settings.llm_client == "fixture":
        return True
    if settings.llm_client == "voicesanj":
        async with get_sessionmaker()() as session:
            runtime = await resolve_provider_settings(session)
        base = (runtime.voicesanj_base_url or "").rstrip("/")
        if not base:
            return False
        key = normalize_api_key(runtime.voicesanj_api_key)
        if not key:
            return False
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(
                f"{base}/v1/models",
                headers={"Authorization": f"Bearer {key}"},
            )
            return response.status_code < 400
    async with get_sessionmaker()() as session:
        runtime = await resolve_provider_settings(session)
    api_key = normalize_api_key(runtime.openai_api_key)
    async with httpx.AsyncClient(timeout=3.0) as client:
        for url in settings.llama_urls:
            if api_key:
                response = await client.get(
                    f"{url}/v1/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
            else:
                response = await client.get(f"{url}/health")
            if response.status_code >= 400:
                return False
    return True


@router.get("/readyz")
async def readyz(response: Response) -> dict[str, Any]:
    checks = {
        "postgres": _check_postgres(),
        "redis": _check_redis(),
        "minio": _check_storage(),
        "llm": _check_llm(),
    }
    results = await asyncio.gather(*checks.values(), return_exceptions=True)
    report: dict[str, Any] = {}
    ready = True
    for name, result in zip(checks.keys(), results, strict=True):
        ok = result is True
        report[name] = "ok" if ok else f"error: {result}"
        ready = ready and ok
    if not ready:
        response.status_code = 503
    return {"status": "ready" if ready else "degraded", "checks": report}


@router.get("/metrics")
async def metrics(request: Request) -> Response:
    """Scrape endpoint; a configured token keeps it off the public internet (§14)."""
    token = get_settings().metrics_token
    if token:
        provided = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        if not compare_digest(provided, token):
            raise ApiError("unauthorized", "metrics token is required")
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
