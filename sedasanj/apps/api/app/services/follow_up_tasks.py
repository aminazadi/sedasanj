"""Promote LLM action items into durable, operator-editable follow-up tasks."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, cast
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiError
from app.models import Call, FollowUpTask, Tenant
from app.schemas import TaskDay, TaskOut, TaskPriority, TaskStatus, TaskUpdate

DEFAULT_TZ = "Asia/Tehran"
TITLE_MAX = 500
DESCRIPTION_MAX = 4000
PRIORITY_RANK = {"high": 0, "normal": 1, "low": 2}


def source_phone_for_call(call: Call) -> str | None:
    if call.direction == "outbound":
        return call.dialed_number or call.caller_number
    return call.caller_number or call.dialed_number


def normalize_title(value: str) -> str:
    return " ".join(value.split())


def titles_from_action_items(action_items: Any) -> list[str]:
    if not isinstance(action_items, list):
        return []
    seen: set[str] = set()
    titles: list[str] = []
    for item in action_items:
        if not isinstance(item, str):
            continue
        title = normalize_title(item)[:TITLE_MAX]
        if not title:
            continue
        key = title.casefold()
        if key in seen:
            continue
        seen.add(key)
        titles.append(title)
    return titles


def today_in_timezone(tz_name: str = DEFAULT_TZ, *, now: datetime | None = None) -> date:
    try:
        zone = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        zone = ZoneInfo(DEFAULT_TZ)
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return current.astimezone(zone).date()


def created_on(task: FollowUpTask, tz_name: str = DEFAULT_TZ) -> date:
    created = task.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    try:
        zone = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        zone = ZoneInfo(DEFAULT_TZ)
    return created.astimezone(zone).date()


def effective_open_date(task: FollowUpTask, tz_name: str = DEFAULT_TZ) -> date:
    if task.due_date is not None:
        return task.due_date
    return created_on(task, tz_name)


def is_today_bucket(task: FollowUpTask, today: date, tz_name: str = DEFAULT_TZ) -> bool:
    return task.status == "open" and effective_open_date(task, tz_name) <= today


def is_upcoming_bucket(task: FollowUpTask, today: date) -> bool:
    return task.status == "open" and task.due_date is not None and task.due_date > today


def _open_sort_key(task: FollowUpTask) -> tuple[int, date, datetime]:
    return (
        PRIORITY_RANK.get(task.priority or "", 3),
        task.due_date or date.max,
        task.created_at,
    )


def serialize(task: FollowUpTask, call: Call) -> TaskOut:
    return TaskOut(
        id=task.id,
        call_id=task.call_id,
        title=task.title,
        description=task.description,
        status=cast(TaskStatus, task.status),
        priority=cast(TaskPriority | None, task.priority),
        due_date=task.due_date,
        source_phone=task.source_phone,
        caller_number=call.caller_number,
        dialed_number=call.dialed_number,
        agent_extension=call.agent_extension,
        created_at=task.created_at,
        completed_at=task.completed_at,
        updated_at=task.updated_at,
    )


def apply_update(
    task: FollowUpTask,
    payload: TaskUpdate,
    *,
    actor_id: UUID,
    now: datetime | None = None,
) -> FollowUpTask:
    stamp = now or datetime.now(UTC)
    fields = payload.model_fields_set
    if "title" in fields:
        if payload.title is None:
            raise ApiError("invalid_request", "title cannot be empty")
        title = normalize_title(payload.title)[:TITLE_MAX]
        if not title:
            raise ApiError("invalid_request", "title cannot be empty")
        task.title = title
    if "description" in fields:
        raw = payload.description
        if raw is None or not raw.strip():
            task.description = None
        else:
            task.description = raw.strip()[:DESCRIPTION_MAX]
    if "priority" in fields:
        task.priority = payload.priority
    if "due_date" in fields:
        task.due_date = payload.due_date
    if "status" in fields and payload.status is not None and payload.status != task.status:
        task.status = payload.status
        if payload.status == "done":
            task.completed_at = stamp
            task.completed_by = actor_id
        else:
            task.completed_at = None
            task.completed_by = None
    task.updated_at = stamp
    return task


async def tenant_today(session: AsyncSession, tenant_id: UUID) -> tuple[date, str]:
    tenant = await session.get(Tenant, tenant_id)
    tz_name = tenant.timezone if tenant and tenant.timezone else DEFAULT_TZ
    return today_in_timezone(tz_name), tz_name


async def sync_from_analysis(
    session: AsyncSession, call: Call, action_items: Any
) -> list[FollowUpTask]:
    titles = titles_from_action_items(action_items)
    if not titles:
        return []
    existing = (
        (
            await session.execute(
                select(FollowUpTask).where(
                    FollowUpTask.call_id == call.id, FollowUpTask.tenant_id == call.tenant_id
                )
            )
        )
        .scalars()
        .all()
    )
    known = {normalize_title(row.title).casefold() for row in existing}
    created: list[FollowUpTask] = []
    phone = source_phone_for_call(call)
    now = datetime.now(UTC)
    for title in titles:
        if title.casefold() in known:
            continue
        task = FollowUpTask(
            tenant_id=call.tenant_id,
            call_id=call.id,
            title=title,
            status="open",
            source_phone=phone,
            created_at=now,
            updated_at=now,
        )
        session.add(task)
        known.add(title.casefold())
        created.append(task)
    return created


async def list_for_call(
    session: AsyncSession, call: Call, action_items: Any | None = None
) -> list[tuple[FollowUpTask, Call]]:
    if action_items is not None:
        await sync_from_analysis(session, call, action_items)
        await session.flush()
    rows = (
        (
            await session.execute(
                select(FollowUpTask)
                .where(FollowUpTask.call_id == call.id, FollowUpTask.tenant_id == call.tenant_id)
                .order_by(FollowUpTask.created_at.asc(), FollowUpTask.id.asc())
            )
        )
        .scalars()
        .all()
    )
    return [(row, call) for row in rows]


def build_board(
    pairs: list[tuple[FollowUpTask, Call]],
    *,
    today: date,
    tz_name: str = DEFAULT_TZ,
) -> tuple[list[TaskOut], list[TaskDay], list[TaskOut]]:
    today_pairs: list[tuple[FollowUpTask, Call]] = []
    upcoming_pairs: list[tuple[FollowUpTask, Call]] = []
    done_pairs: list[tuple[FollowUpTask, Call]] = []
    for task, call in pairs:
        if task.status == "done":
            done_pairs.append((task, call))
        elif is_today_bucket(task, today, tz_name):
            today_pairs.append((task, call))
        elif is_upcoming_bucket(task, today):
            upcoming_pairs.append((task, call))
        else:
            today_pairs.append((task, call))

    today_pairs.sort(key=lambda pair: _open_sort_key(pair[0]))
    upcoming_pairs.sort(key=lambda pair: (pair[0].due_date or date.max, _open_sort_key(pair[0])))
    done_pairs.sort(
        key=lambda pair: pair[0].completed_at or pair[0].updated_at,
        reverse=True,
    )

    upcoming_groups: dict[date, list[TaskOut]] = {}
    upcoming_order: list[date] = []
    for task, call in upcoming_pairs:
        due = task.due_date
        if due is None:
            continue
        if due not in upcoming_groups:
            upcoming_groups[due] = []
            upcoming_order.append(due)
        upcoming_groups[due].append(serialize(task, call))

    return (
        [serialize(task, call) for task, call in today_pairs],
        [TaskDay(date=day, items=upcoming_groups[day]) for day in upcoming_order],
        [serialize(task, call) for task, call in done_pairs],
    )
