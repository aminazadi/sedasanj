from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Query, Request
from sqlalchemy import Select, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.deps import OperatorDep, Principal, TenantSession, UserDep, client_ip
from app.errors import ApiError
from app.models import Call, CallOperatorAssignment, FollowUpTask, FollowUpTaskEvent, User
from app.schemas import (
    TaskCreate,
    TaskEventOut,
    TaskHistoryPage,
    TaskNote,
    TaskOut,
    TaskPage,
    TaskPerson,
    TaskPriority,
    TaskStatus,
    TaskUpdate,
)
from app.services import audit, follow_up_tasks, operator_scope

router = APIRouter(prefix="/v1", tags=["tasks"])
TaskView = Literal["overdue", "today", "upcoming", "done", "all"]
TaskSort = Literal["due_date", "priority", "created_at", "updated_at"]


def _visible_task_stmt(principal: Principal) -> Select[tuple[FollowUpTask, Call]]:
    stmt = (
        select(FollowUpTask, Call)
        .join(Call, Call.id == FollowUpTask.call_id)
        .where(FollowUpTask.tenant_id == principal.tenant_id, Call.tenant_id == principal.tenant_id)
    )
    return operator_scope.apply_operator_scope(stmt, principal)


async def _load_visible_task(
    session: AsyncSession, task_id: UUID, principal: Principal, *, lock: bool = False
) -> tuple[FollowUpTask, Call]:
    stmt = _visible_task_stmt(principal).where(FollowUpTask.id == task_id)
    if lock:
        stmt = stmt.with_for_update(of=FollowUpTask).execution_options(populate_existing=True)
    row = (await session.execute(stmt)).first()
    if row is None:
        raise ApiError("not_found", "task not found; return to the task list and refresh")
    return row[0], row[1]


async def _visible_call(session: AsyncSession, call_id: UUID, principal: Principal) -> Call:
    stmt = operator_scope.apply_operator_scope(
        select(Call).where(Call.id == call_id, Call.tenant_id == principal.tenant_id), principal
    )
    call = (await session.execute(stmt)).scalar_one_or_none()
    if call is None:
        raise ApiError("not_found", "call not found; choose an accessible call")
    if call.direction == "internal":
        raise ApiError("invalid_request", "choose a customer call instead of an internal call")
    return cast(Call, call)


def _eligible_users(principal: Principal, call_id: UUID) -> Select[tuple[User]]:
    assigned = (
        select(CallOperatorAssignment.id)
        .where(
            CallOperatorAssignment.tenant_id == principal.tenant_id,
            CallOperatorAssignment.call_id == call_id,
            CallOperatorAssignment.operator_id == User.id,
            CallOperatorAssignment.superseded_at.is_(None),
        )
        .exists()
    )
    return select(User).where(
        User.tenant_id == principal.tenant_id,
        or_(User.role == "org_admin", (User.role == "operator") & assigned),
    )


async def _outputs(
    session: AsyncSession, pairs: list[tuple[FollowUpTask, Call]], principal: Principal
) -> list[TaskOut]:
    ids = {task.assignee_id for task, _ in pairs if task.assignee_id}
    users = (
        {
            u.id: u
            for u in (
                await session.scalars(
                    select(User).where(User.tenant_id == principal.tenant_id, User.id.in_(ids))
                )
            ).all()
        }
        if ids
        else {}
    )
    call_ids = {task.call_id for task, _ in pairs}
    active = (
        set(
            (
                await session.execute(
                    select(
                        CallOperatorAssignment.call_id, CallOperatorAssignment.operator_id
                    ).where(
                        CallOperatorAssignment.tenant_id == principal.tenant_id,
                        CallOperatorAssignment.call_id.in_(call_ids),
                        CallOperatorAssignment.operator_id.in_(ids),
                        CallOperatorAssignment.superseded_at.is_(None),
                    )
                )
            ).all()
        )
        if ids
        else set()
    )
    assert principal.tenant_id is not None
    today, _ = await follow_up_tasks.tenant_today(session, principal.tenant_id)
    result = []
    for task, call in pairs:
        output = follow_up_tasks.serialize(task, call, today=today)
        person = users.get(task.assignee_id) if task.assignee_id else None
        output.assignee_name = (person.display_name or person.email) if person else None
        output.assignee_access_valid = task.assignee_id is None or bool(
            person
            and (
                person.role == "org_admin"
                or (person.role == "operator" and (task.call_id, person.id) in active)
            )
        )
        result.append(output)
    return result


def _buckets(today: date) -> dict[str, ColumnElement[bool]]:
    pending = FollowUpTask.status.in_(["open", "in_progress"])
    return {
        "overdue": pending & (FollowUpTask.due_date < today),
        "today": pending & or_(FollowUpTask.due_date.is_(None), FollowUpTask.due_date <= today),
        "upcoming": pending & (FollowUpTask.due_date > today),
        "done": FollowUpTask.status == "done",
    }


@router.get("/tasks", response_model=TaskPage)
async def list_tasks(
    principal: UserDep,
    session: TenantSession,
    view: TaskView = "today",
    q: str = Query(default="", max_length=200),
    status: TaskStatus | None = None,
    priority: TaskPriority | None = None,
    assignee_id: UUID | None = None,
    unassigned: bool = False,
    due_from: date | None = None,
    due_to: date | None = None,
    sort: TaskSort = "due_date",
    order: Literal["asc", "desc"] = "asc",
    limit: int = Query(default=25, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> TaskPage:
    assert principal.tenant_id is not None
    if due_from and due_to and due_from > due_to:
        raise ApiError("invalid_request", "due_from must precede due_to; correct the date range")
    today, _ = await follow_up_tasks.tenant_today(session, principal.tenant_id)
    stmt = _visible_task_stmt(principal)
    if q.strip():
        search = q.strip().translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))
        stmt = stmt.where(
            or_(
                *[
                    column.icontains(search, autoescape=True)
                    for column in (
                        FollowUpTask.title,
                        FollowUpTask.description,
                        FollowUpTask.source_phone,
                        Call.caller_number,
                        Call.dialed_number,
                    )
                ]
            )
        )
    if status:
        stmt = stmt.where(FollowUpTask.status == status)
    if priority:
        stmt = stmt.where(FollowUpTask.priority == priority)
    if assignee_id:
        stmt = stmt.where(FollowUpTask.assignee_id == assignee_id)
    if unassigned:
        stmt = stmt.where(FollowUpTask.assignee_id.is_(None))
    if due_from:
        stmt = stmt.where(FollowUpTask.due_date >= due_from)
    if due_to:
        stmt = stmt.where(FollowUpTask.due_date <= due_to)
    buckets = _buckets(today)
    count_stmt = stmt.with_only_columns(
        func.count(), *[func.count().filter(condition) for condition in buckets.values()]
    ).order_by(None)
    values = (await session.execute(count_stmt)).one()
    counts = {"all": int(values[0]), **{key: int(values[i + 1]) for i, key in enumerate(buckets)}}
    if view != "all":
        stmt = stmt.where(buckets[view])
    total = counts[view]
    column = {
        "due_date": FollowUpTask.due_date,
        "priority": case(
            (FollowUpTask.priority == "high", 0),
            (FollowUpTask.priority == "normal", 1),
            (FollowUpTask.priority == "low", 2),
            else_=3,
        ),
        "created_at": FollowUpTask.created_at,
        "updated_at": FollowUpTask.updated_at,
    }[sort]
    ordering = column.desc() if order == "desc" else column.asc()
    rows = (
        await session.execute(
            stmt.order_by(ordering.nulls_last(), FollowUpTask.id).limit(limit).offset(offset)
        )
    ).all()
    return TaskPage(
        items=await _outputs(session, [(r[0], r[1]) for r in rows], principal),
        total=total,
        limit=limit,
        offset=offset,
        counts=counts,
        today=today,
    )


@router.get("/tasks/people", response_model=list[TaskPerson])
async def task_people(principal: UserDep, session: TenantSession) -> list[TaskPerson]:
    stmt = select(User).where(
        User.tenant_id == principal.tenant_id, User.role.in_(["org_admin", "operator"])
    )
    if principal.role != "org_admin":
        stmt = stmt.where(or_(User.role == "org_admin", User.id == principal.id))
    return [
        TaskPerson(id=u.id, name=u.display_name or u.email)
        for u in (await session.scalars(stmt.order_by(User.display_name, User.id))).all()
    ]


@router.get("/tasks/assignees", response_model=list[TaskPerson])
async def task_assignees(
    call_id: UUID, principal: UserDep, session: TenantSession
) -> list[TaskPerson]:
    await _visible_call(session, call_id, principal)
    if principal.role != "org_admin":
        raise ApiError("forbidden", "only organization administrators can assign tasks")
    return [
        TaskPerson(id=u.id, name=u.display_name or u.email)
        for u in (await session.scalars(_eligible_users(principal, call_id))).all()
    ]


@router.get("/tasks/{task_id}", response_model=TaskOut)
async def task_detail(task_id: UUID, principal: UserDep, session: TenantSession) -> TaskOut:
    pair = await _load_visible_task(session, task_id, principal)
    return (await _outputs(session, [pair], principal))[0]


@router.get("/tasks/{task_id}/history", response_model=TaskHistoryPage)
async def task_history(
    task_id: UUID,
    principal: UserDep,
    session: TenantSession,
    limit: int = Query(default=25, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> TaskHistoryPage:
    await _load_visible_task(session, task_id, principal)
    where = (
        FollowUpTaskEvent.task_id == task_id,
        FollowUpTaskEvent.tenant_id == principal.tenant_id,
    )
    total = await session.scalar(select(func.count()).select_from(FollowUpTaskEvent).where(*where))
    rows = (
        await session.execute(
            select(FollowUpTaskEvent, User.display_name, User.email)
            .outerjoin(
                User,
                (User.id == FollowUpTaskEvent.actor_id)
                & (User.tenant_id == FollowUpTaskEvent.tenant_id),
            )
            .where(*where)
            .order_by(FollowUpTaskEvent.created_at.desc(), FollowUpTaskEvent.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return TaskHistoryPage(
        items=[
            TaskEventOut(
                id=e.id,
                actor_id=e.actor_id,
                actor_name=name or email,
                kind=e.kind,
                changes=e.changes,
                note=e.note,
                created_at=e.created_at,
            )
            for e, name, email in rows
        ],
        total=int(total or 0),
        limit=limit,
        offset=offset,
    )


def _check_version(task: FollowUpTask, version: int | None) -> None:
    if version != task.version:
        raise ApiError(
            "task_version_conflict", "task changed; refresh the task and retry your edit"
        )


async def _record(
    session: AsyncSession,
    task: FollowUpTask,
    principal: Principal,
    request: Request,
    *,
    kind: str,
    changes: dict[str, Any] | None = None,
    note: str | None = None,
) -> None:
    session.add(
        FollowUpTaskEvent(
            tenant_id=task.tenant_id,
            task_id=task.id,
            actor_id=principal.id,
            kind=kind,
            changes=changes or {},
            note=note,
            created_at=datetime.now(UTC),
        )
    )
    await audit.record(
        session,
        actor_type="user",
        actor_id=principal.id,
        tenant_id=principal.tenant_id,
        action=f"task.{kind}",
        payload={
            "task_id": str(task.id),
            "call_id": str(task.call_id),
            "fields": sorted(changes or {}),
            "version": task.version,
        },
        ip=client_ip(request),
    )


@router.post("/tasks", response_model=TaskOut, status_code=201)
async def create_task(
    payload: TaskCreate,
    request: Request,
    principal: OperatorDep,
    session: TenantSession,
) -> TaskOut:
    call = await _visible_call(session, payload.call_id, principal)
    title = follow_up_tasks.normalize_title(payload.title)
    if not title:
        raise ApiError("invalid_request", "enter a non-empty task title")
    task = FollowUpTask(
        tenant_id=principal.tenant_id,
        call_id=call.id,
        title=title,
        description=(payload.description or "").strip() or None,
        priority=payload.priority,
        due_date=payload.due_date,
        source_phone=follow_up_tasks.source_phone_for_call(call),
        origin="manual",
        status="open",
        version=1,
    )
    session.add(task)
    await session.flush()
    await _record(session, task, principal, request, kind="created")
    return (await _outputs(session, [(task, call)], principal))[0]


@router.patch("/tasks/{task_id}", response_model=TaskOut)
async def update_task(
    task_id: UUID,
    payload: TaskUpdate,
    request: Request,
    principal: OperatorDep,
    session: TenantSession,
) -> TaskOut:
    fields = payload.model_fields_set - {"version"}
    if not fields:
        raise ApiError("invalid_request", "choose a task field to update")
    task, call = await _load_visible_task(session, task_id, principal, lock=True)
    _check_version(task, payload.version)
    if "assignee_id" in fields:
        if principal.role != "org_admin":
            raise ApiError("forbidden", "ask an organization administrator to change the assignee")
        if payload.assignee_id is not None:
            eligible = await session.scalar(
                _eligible_users(principal, call.id).where(User.id == payload.assignee_id)
            )
            if eligible is None:
                raise ApiError("task_assignee_invalid", "select a person with current call access")
    previous_updated_at = task.updated_at
    before = follow_up_tasks.serialize(task, call).model_dump(mode="json")
    follow_up_tasks.apply_update(task, payload, actor_id=principal.id)
    if "assignee_id" in fields:
        task.assignee_id = payload.assignee_id
    after = follow_up_tasks.serialize(task, call).model_dump(mode="json")
    changes = {
        key: {"before": before[key], "after": after[key]}
        for key in sorted(fields)
        if before[key] != after[key]
    }
    if changes:
        task.version += 1
        await _record(session, task, principal, request, kind="updated", changes=changes)
    else:
        task.updated_at = previous_updated_at
    return (await _outputs(session, [(task, call)], principal))[0]


@router.post("/tasks/{task_id}/notes", response_model=TaskOut, status_code=201)
async def add_note(
    task_id: UUID,
    payload: TaskNote,
    request: Request,
    principal: OperatorDep,
    session: TenantSession,
) -> TaskOut:
    task, call = await _load_visible_task(session, task_id, principal, lock=True)
    _check_version(task, payload.version)
    note = payload.note.strip()
    if not note:
        raise ApiError("invalid_request", "enter a non-empty follow-up note")
    task.version += 1
    task.updated_at = datetime.now(UTC)
    await _record(session, task, principal, request, kind="note", note=note)
    return (await _outputs(session, [(task, call)], principal))[0]
