from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.errors import ApiError
from app.schemas import TaskUpdate
from app.services import follow_up_tasks as tasks


def _call(**overrides: object) -> SimpleNamespace:
    values = {
        "id": uuid4(),
        "tenant_id": uuid4(),
        "caller_number": "09120000000",
        "dialed_number": "02191000000",
        "direction": "inbound",
        "agent_extension": "101",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _task(**overrides: object) -> SimpleNamespace:
    now = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
    values = {
        "id": uuid4(),
        "tenant_id": uuid4(),
        "call_id": uuid4(),
        "title": "تماس مجدد",
        "description": None,
        "status": "open",
        "priority": None,
        "due_date": None,
        "source_phone": "09120000000",
        "created_at": now,
        "updated_at": now,
        "completed_at": None,
        "completed_by": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_source_phone_uses_caller_for_inbound_and_internal() -> None:
    inbound = _call(direction="inbound")
    assert tasks.source_phone_for_call(inbound) == "09120000000"
    internal = _call(direction="internal", caller_number=None, dialed_number="200")
    assert tasks.source_phone_for_call(internal) == "200"


def test_source_phone_uses_dialed_number_for_outbound() -> None:
    call = _call(direction="outbound")
    assert tasks.source_phone_for_call(call) == "02191000000"


def test_titles_from_action_items_trims_and_deduplicates() -> None:
    titles = tasks.titles_from_action_items(
        ["  تماس مجدد  ", "تماس مجدد", "", None, "ارسال پیش‌فاکتور", 12]
    )
    assert titles == ["تماس مجدد", "ارسال پیش‌فاکتور"]


def test_open_tasks_without_due_date_land_in_today() -> None:
    created = datetime(2026, 9, 18, 8, 0, tzinfo=UTC)
    task = _task(created_at=created, due_date=None, status="open")
    today = date(2026, 9, 21)
    assert tasks.is_today_bucket(task, today)
    assert not tasks.is_upcoming_bucket(task, today)


def test_overdue_open_tasks_roll_into_today() -> None:
    task = _task(due_date=date(2026, 9, 19), status="open")
    today = date(2026, 9, 21)
    assert tasks.is_today_bucket(task, today)
    assert not tasks.is_upcoming_bucket(task, today)


def test_future_due_date_stays_in_upcoming() -> None:
    task = _task(due_date=date(2026, 9, 25), status="open")
    today = date(2026, 9, 21)
    assert not tasks.is_today_bucket(task, today)
    assert tasks.is_upcoming_bucket(task, today)


def test_done_tasks_are_excluded_from_open_buckets() -> None:
    task = _task(due_date=date(2026, 9, 19), status="done")
    today = date(2026, 9, 21)
    assert not tasks.is_today_bucket(task, today)
    assert not tasks.is_upcoming_bucket(task, today)


def test_build_board_groups_rollover_upcoming_and_done() -> None:
    call = _call()
    overdue = _task(title="عقب‌افتاده", due_date=date(2026, 9, 19), status="open")
    undated = _task(title="بدون موعد", due_date=None, status="open")
    later = _task(title="فردا", due_date=date(2026, 9, 22), status="open")
    done = _task(
        title="تمام",
        status="done",
        completed_at=datetime(2026, 9, 20, 16, 0, tzinfo=UTC),
    )
    today_items, upcoming, completed = tasks.build_board(
        [(overdue, call), (undated, call), (later, call), (done, call)],
        today=date(2026, 9, 21),
    )
    assert [item.title for item in today_items] == ["عقب‌افتاده", "بدون موعد"]
    assert len(upcoming) == 1
    assert upcoming[0].date == date(2026, 9, 22)
    assert upcoming[0].items[0].title == "فردا"
    assert completed[0].title == "تمام"


def test_apply_update_marks_done_and_can_reopen() -> None:
    task = _task()
    actor = uuid4()
    now = datetime(2026, 9, 21, 10, 0, tzinfo=UTC)
    tasks.apply_update(task, TaskUpdate(status="done"), actor_id=actor, now=now)
    assert task.status == "done"
    assert task.completed_at == now
    assert task.completed_by == actor
    tasks.apply_update(task, TaskUpdate(status="open"), actor_id=actor, now=now)
    assert task.status == "open"
    assert task.completed_at is None
    assert task.completed_by is None


def test_apply_update_can_clear_due_date_and_priority() -> None:
    task = _task(due_date=date(2026, 9, 22), priority="high")
    payload = TaskUpdate.model_validate(
        {"due_date": None, "priority": None, "description": "  پیگیری شد  "}
    )
    tasks.apply_update(task, payload, actor_id=uuid4())
    assert task.due_date is None
    assert task.priority is None
    assert task.description == "پیگیری شد"


def test_apply_update_rejects_blank_title() -> None:
    task = _task()
    with pytest.raises(ApiError) as excinfo:
        tasks.apply_update(task, TaskUpdate(title="   "), actor_id=uuid4())
    assert excinfo.value.code == "invalid_request"


def test_today_in_tehran_does_not_flip_on_utc_evening() -> None:
    now = datetime(2026, 9, 21, 21, 30, tzinfo=UTC)
    assert tasks.today_in_timezone("Asia/Tehran", now=now) == date(2026, 9, 22)
    assert tasks.today_in_timezone("UTC", now=now) == date(2026, 9, 21)
