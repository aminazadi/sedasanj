"""Public catalogue of the Jalase-Negar app: categories, plans and token packs.

Nothing here is personal, so no sign-in is needed. The app can show what is for sale before the
user signs in, and the responses carry an ETag so a cached copy is reused cheaply.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from fastapi import APIRouter, Request, Response, status
from sqlalchemy import select

from app.db import control_session_scope
from app.deps import client_ip
from app.models import TokenPackage
from app.services import jalase_billing, jalase_output_types, platform, ratelimit

router = APIRouter(prefix="/v1/jalase-negar/catalog", tags=["jalase-negar-catalog"])

CACHE_CONTROL = "public, max-age=300"
RATE_LIMIT_PER_MINUTE = 120


async def _enforce_public_rate(request: Request) -> None:
    await ratelimit.enforce(
        f"jn-catalog:{client_ip(request) or 'unknown'}", RATE_LIMIT_PER_MINUTE, 60
    )


def _respond(request: Request, payload: Any) -> Response:
    """JSON with a strong ETag; a matching If-None-Match gets 304 with no body."""
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    etag = '"' + hashlib.sha256(body).hexdigest()[:32] + '"'
    headers = {"ETag": etag, "Cache-Control": CACHE_CONTROL}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)
    return Response(content=body, media_type="application/json", headers=headers)


@router.get("/output-types")
async def catalog_output_types(request: Request) -> Response:
    """Published categories with their input fields; the built-in minutes comes first."""
    await _enforce_public_rate(request)
    async with control_session_scope() as session:
        items = await jalase_output_types.published_catalog(session)
    return _respond(request, {"items": items})


@router.get("/plans")
async def catalog_plans(request: Request) -> Response:
    """Public monthly plans (with the free plan) and their allowance in hours."""
    await _enforce_public_rate(request)
    async with control_session_scope() as session:
        paid = await jalase_billing.plans(session)
        free = await jalase_billing.free_plan(session)
    return _respond(request, {"free": free, "plans": paid})


@router.get("/token-packages")
async def catalog_token_packages(request: Request) -> Response:
    """Token top-up packs for the app's store (sold in addition to plans)."""
    await _enforce_public_rate(request)
    async with control_session_scope() as session:
        rows = (
            (
                await session.execute(
                    select(TokenPackage)
                    .where(TokenPackage.active.is_(True), TokenPackage.product == "jalase_negar")
                    .order_by(TokenPackage.tokens)
                )
            )
            .scalars()
            .all()
        )
        per_hour = await platform.jalase_tokens_per_hour(session)
    items = [
        {
            "id": str(row.id),
            "name": row.name,
            "hours": jalase_billing.to_hours(row.tokens, per_hour),
            "price_toman": row.price_toman,
        }
        for row in rows
    ]
    return _respond(request, {"items": items})
