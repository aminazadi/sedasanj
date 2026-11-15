"""Admin management of the Jalase-Negar badges (achievements) and their gift tokens."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.deps import StaffDep, StaffSession, SuperAdminDep, client_ip
from app.errors import ApiError
from app.models import JalaseAchievement
from app.services import audit

router = APIRouter(prefix="/v1/admin/jalase/achievements", tags=["admin"])

Metric = Literal["meetings", "documents", "categories", "streak_weeks"]


class AchievementCreate(BaseModel):
    code: str = Field(pattern=r"^[a-z0-9_]{2,48}$")
    title_fa: str = Field(min_length=2, max_length=80)
    description_fa: str = Field(min_length=2, max_length=300)
    metric: Metric
    threshold: int = Field(ge=1, le=100_000)
    reward_tokens: int = Field(ge=0, le=5_000_000)
    sort_order: int = Field(default=0, ge=0, le=100_000)
    active: bool = True


class AchievementUpdate(BaseModel):
    title_fa: str | None = Field(default=None, min_length=2, max_length=80)
    description_fa: str | None = Field(default=None, min_length=2, max_length=300)
    threshold: int | None = Field(default=None, ge=1, le=100_000)
    reward_tokens: int | None = Field(default=None, ge=0, le=5_000_000)
    sort_order: int | None = Field(default=None, ge=0, le=100_000)
    active: bool | None = None


def _out(row: JalaseAchievement) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "code": row.code,
        "title_fa": row.title_fa,
        "description_fa": row.description_fa,
        "metric": row.metric,
        "threshold": row.threshold,
        "reward_tokens": row.reward_tokens,
        "sort_order": row.sort_order,
        "active": row.active,
    }


@router.get("")
async def list_achievements(_: StaffDep, session: StaffSession) -> list[dict[str, Any]]:
    rows = await session.execute(
        select(JalaseAchievement).order_by(JalaseAchievement.sort_order, JalaseAchievement.code)
    )
    return [_out(row) for row in rows.scalars()]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_achievement(
    payload: AchievementCreate, request: Request, staff: SuperAdminDep, session: StaffSession
) -> dict[str, Any]:
    row = JalaseAchievement(**payload.model_dump())
    try:
        async with session.begin_nested():
            session.add(row)
            await session.flush()
    except IntegrityError as error:
        raise ApiError("conflict_idempotency", "این کد نشان قبلاً ثبت شده است.") from error
    await audit.record(
        session,
        actor_type="staff",
        actor_id=staff.id,
        action="jalase_achievement.created",
        payload={"code": row.code, "reward_tokens": row.reward_tokens},
        ip=client_ip(request),
    )
    return _out(row)


@router.patch("/{achievement_id}")
async def update_achievement(
    achievement_id: UUID,
    payload: AchievementUpdate,
    request: Request,
    staff: SuperAdminDep,
    session: StaffSession,
) -> dict[str, Any]:
    row = await session.get(JalaseAchievement, achievement_id, with_for_update=True)
    if row is None:
        raise ApiError("not_found", "نشان پیدا نشد؛ صفحه را تازه کنید.")
    changes = payload.model_dump(exclude_none=True)
    for key, value in changes.items():
        setattr(row, key, value)
    row.updated_at = func.now()
    await audit.record(
        session,
        actor_type="staff",
        actor_id=staff.id,
        action="jalase_achievement.updated",
        payload={"code": row.code, "fields": sorted(changes)},
        ip=client_ip(request),
    )
    return _out(row)
