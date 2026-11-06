"""Jalase-Negar "meet SedaSanj" drawer: public read for the app, super-admin write."""

from typing import Any

from fastapi import APIRouter, Request, Response

from app.db import control_session_scope
from app.deps import StaffSession, SuperAdminDep, client_ip
from app.services import audit, ratelimit
from app.services import jalase_sedasanj_intro as intro

router = APIRouter(tags=["jalase-negar updates"])
# Under /v1/jalase-negar/android/ so the app-wide no-store header applies.
PUBLIC = "/v1/jalase-negar/android/sedasanj-intro"
ADMIN = "/v1/admin/jalase-negar/sedasanj-intro"


@router.get(PUBLIC)
async def public_intro(request: Request, response: Response) -> dict[str, Any]:
    await ratelimit.enforce(f"jalase-intro:{client_ip(request)}", 60, 60)
    async with control_session_scope() as session:
        value = await intro.load(session)
    return value.model_dump()


@router.get(ADMIN)
async def read_intro(session: StaffSession, _: SuperAdminDep) -> dict[str, Any]:
    return (await intro.load(session)).model_dump()


@router.put(ADMIN)
async def save_intro(
    payload: intro.SedasanjIntro,
    request: Request,
    session: StaffSession,
    principal: SuperAdminDep,
) -> dict[str, Any]:
    await intro.save(session, payload)
    await audit.record(
        session,
        actor_type="staff",
        actor_id=principal.id,
        action="jalase_negar.sedasanj_intro_update",
        payload={"enabled": payload.enabled, "has_video": bool(payload.video_url)},
        ip=client_ip(request),
    )
    return payload.model_dump()
