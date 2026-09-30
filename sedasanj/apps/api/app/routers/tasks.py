from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request
from sqlalchemy import Select, select

from app.deps import OperatorDep, Principal, TenantSession, UserDep, client_ip
from app.errors import ApiError
from app.models import Call, FollowUpTask
from app.schemas import TaskBoard, TaskOut, TaskUpdate
from app.services import audit, follow_up_tasks, operator_scope

router = APIRouter(prefix="/v1", tags=["tasks"])


def _visible_task_stmt(principal: Principal) -> Select[tuple[FollowUpTask, Call]]:
    assert principal.tenant_id is not None
    stmt = (
        select(FollowUpTask, Call)
        .join(Call, Call.id == FollowUpTask.call_id)
        .where(
            FollowUpTask.tenant_id == principal.tenant_id,
            Call.tenant_id == principal.tenant_id,
        )
    )
    return operator_scope.apply_operator_scope(stmt, principal)


async def _load_visible_task(
    session: TenantSession, task_id: UUID, principal: UserDep
) -> tuple[FollowUpTask, Call]:
    row = (
        await session.execute(_visible_task_stmt(principal).where(FollowUpTask.id == task_id))
    ).first()
    if row is None:
        raise ApiError("not_found", "task not found")
    return row[0], row[1]


@router.get("/tasks", response_model=TaskBoard)
async def list_tasks(principal: UserDep, session: TenantSession) -> TaskBoard:
    assert principal.tenant_id is not None
    today, tz_name = await follow_up_tasks.tenant_today(session, principal.tenant_id)
    rows = (await session.execute(_visible_task_stmt(principal))).all()
    pairs = [(task, call) for task, call in rows]
    today_items, upcoming, completed = follow_up_tasks.build_board(
        pairs, today=today, tz_name=tz_name
    )
    upcoming_count = sum(len(day.items) for day in upcoming)
    return TaskBoard(
        today=today_items,
        upcoming=upcoming,
        completed=completed,
        open_count=len(today_items) + upcoming_count,
        today_count=len(today_items),
        upcoming_count=upcoming_count,
        completed_count=len(completed),
    )


@router.patch("/tasks/{task_id}", response_model=TaskOut)
async def update_task(
    task_id: UUID,
    payload: TaskUpdate,
    request: Request,
    principal: OperatorDep,
    session: TenantSession,
) -> TaskOut:
    assert principal.tenant_id is not None
    if not payload.model_fields_set:
        raise ApiError("invalid_request", "no fields to update")
    task, call = await _load_visible_task(session, task_id, principal)
    follow_up_tasks.apply_update(task, payload, actor_id=principal.id)
    await audit.record(
        session,
        actor_type="user",
        actor_id=principal.id,
        tenant_id=principal.tenant_id,
        action="task.update",
        payload={
            "task_id": str(task.id),
            "call_id": str(call.id),
            "fields": sorted(payload.model_fields_set),
            "status": task.status,
        },
        ip=client_ip(request),
    )
    return follow_up_tasks.serialize(task, call)
