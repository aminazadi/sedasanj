from __future__ import annotations

from types import SimpleNamespace

import pytest

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
