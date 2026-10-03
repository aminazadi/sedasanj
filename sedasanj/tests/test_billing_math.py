from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.models import CreditReservation, Tenant
from app.services import billing
from app.services.billing import billable_seconds, normalize_balance_cache, seconds_to_toman


@pytest.mark.parametrize(
    ("duration_ms", "expected"),
    [
        (1, 30),
        (1_000, 30),
        (29_999, 30),
        (30_000, 30),
        (30_001, 31),
        (61_500, 62),
        (3_600_000, 3600),
    ],
)
def test_billable_seconds_has_a_thirty_second_floor(duration_ms: int, expected: int) -> None:
    assert billable_seconds(duration_ms) == expected


def test_seconds_to_toman_rounds_up_partial_minutes() -> None:
    assert seconds_to_toman(60, 10_000) == 10_000
    assert seconds_to_toman(30, 10_000) == 5_000
    assert seconds_to_toman(31, 10_000) == 5_167


def test_settlement_delta_never_exceeds_the_reservation() -> None:
    """A shorter measured duration must not bill more than what was held."""
    reserved = billable_seconds(120_000)
    actual = billable_seconds(90_000)
    assert actual <= reserved
    assert reserved - actual == 30


def test_normalize_balance_cache_repairs_legacy_nulls() -> None:
    cache = SimpleNamespace(seconds=None, toman=None)

    normalized = normalize_balance_cache(cache)  # type: ignore[arg-type]

    assert normalized.seconds == 0
    assert normalized.toman == 0


class _NoHeldResult:
    def scalar_one_or_none(self) -> None:
        return None


class _ValueResult:
    def __init__(self, value: object | None) -> None:
        self.value = value

    def scalar_one_or_none(self) -> object | None:
        return self.value


@pytest.mark.asyncio
async def test_retry_reservation_uses_a_distinct_idempotency_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant = Tenant(id=uuid4(), price_per_minute_toman=10_000)
    call_id = uuid4()
    cache = SimpleNamespace(seconds=600, toman=100_000)
    added: list[object] = []

    class Session:
        execute = AsyncMock(return_value=_NoHeldResult())

        def add(self, value: object) -> None:
            added.append(value)

        async def flush(self) -> None:
            for value in added:
                if isinstance(value, CreditReservation) and value.id is None:
                    value.id = uuid4()

    applied: dict[str, object] = {}
    monkeypatch.setattr(billing, "_lock_cache", AsyncMock(return_value=cache))
    monkeypatch.setattr(billing, "_ensure_legacy_grant", AsyncMock())
    monkeypatch.setattr(billing, "_allocate_grants", AsyncMock())

    async def apply(*args: object, **kwargs: object) -> None:
        applied.update(kwargs)

    monkeypatch.setattr(billing, "_apply", apply)
    reservation = await billing.reserve_retry(
        Session(),  # type: ignore[arg-type]
        tenant=tenant,
        call_id=call_id,
        duration_ms=57_000,
    )

    assert reservation.status == "held"
    assert reservation.seconds == 57
    assert applied["idempotency_key"] == f"reserve:{call_id}:{reservation.id}"
    assert applied["seconds_delta"] == -57


@pytest.mark.asyncio
async def test_repeated_failures_release_each_retry_reservation_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid4()
    call_id = uuid4()
    reservations = [
        CreditReservation(
            id=uuid4(),
            tenant_id=tenant_id,
            call_id=call_id,
            seconds=57,
            toman=9_500,
            status="held",
        )
        for _ in range(2)
    ]
    keys: list[str] = []

    class Session:
        def __init__(self, reservation: CreditReservation) -> None:
            self.results = iter([_ValueResult(reservation), _ValueResult(None)])

        async def execute(self, statement: object) -> _ValueResult:
            return next(self.results)

    monkeypatch.setattr(billing, "_existing_entry", AsyncMock(return_value=None))
    monkeypatch.setattr(billing, "_restore_allocations", AsyncMock(return_value=57))

    async def apply(*args: object, **kwargs: object) -> None:
        keys.append(str(kwargs["idempotency_key"]))

    monkeypatch.setattr(billing, "_apply", apply)

    for reservation in reservations:
        await billing.release(
            Session(reservation),  # type: ignore[arg-type]
            tenant_id=tenant_id,
            call_id=call_id,
        )

    assert keys == [
        f"release:{call_id}:{reservations[0].id}",
        f"release:{call_id}:{reservations[1].id}",
    ]


@pytest.mark.asyncio
async def test_successful_retry_settles_the_call_only_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid4()
    call_id = uuid4()
    reservation = CreditReservation(
        id=uuid4(),
        tenant_id=tenant_id,
        call_id=call_id,
        seconds=57,
        toman=9_500,
        status="held",
    )
    tenant = Tenant(id=tenant_id, price_per_minute_toman=10_000)
    applied: list[str] = []

    class Session:
        def __init__(self, results: list[object | None]) -> None:
            self.results = iter(_ValueResult(value) for value in results)

        async def execute(self, statement: object) -> _ValueResult:
            return next(self.results)

    async def apply(*args: object, **kwargs: object) -> None:
        applied.append(str(kwargs["idempotency_key"]))

    monkeypatch.setattr(billing, "_apply", apply)
    first = await billing.settle(
        Session([reservation, tenant, None, None]),  # type: ignore[arg-type]
        tenant_id=tenant_id,
        call_id=call_id,
        actual_duration_ms=57_000,
    )
    repeated = await billing.settle(
        Session([None, uuid4()]),  # type: ignore[arg-type]
        tenant_id=tenant_id,
        call_id=call_id,
        actual_duration_ms=57_000,
    )

    assert first == repeated == 57
    assert applied == [f"settle:{call_id}:{reservation.id}"]
