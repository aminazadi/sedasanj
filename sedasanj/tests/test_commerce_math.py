from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.errors import ApiError
from app.services.commerce import add_months, prorated_amount, subscription_amount
from app.services.quotas import monthly_period_end, monthly_period_start


def version(**overrides: object) -> SimpleNamespace:
    values = {
        "annual_price_toman": 49_990_000,
        "allows_extra_operators": True,
        "extra_operator_annual_toman": 1_990_000,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_gold_extra_operator_pricing() -> None:
    assert subscription_amount(version(), "annual", 2) == (53_970_000, 1_990_000)
    with pytest.raises(ApiError):
        subscription_amount(version(), "monthly", 2)


@pytest.mark.parametrize(
    ("annual_price", "expected"),
    ((9_900_000, 9_900_000), (29_900_000, 29_900_000), (59_900_000, 59_900_000)),
)
def test_annual_plan_price_is_charged_in_full(annual_price: int, expected: int) -> None:
    plan = version(annual_price_toman=annual_price, allows_extra_operators=False)

    assert subscription_amount(plan, "annual", 0) == (expected, 0)


def test_extra_operator_is_rejected_for_other_plans() -> None:
    with pytest.raises(ApiError):
        subscription_amount(version(allows_extra_operators=False), "annual", 1)


def test_calendar_month_math_clamps_end_of_month() -> None:
    assert add_months(datetime(2026, 1, 31, tzinfo=UTC), 1) == datetime(
        2026, 2, 28, tzinfo=UTC
    )


def test_monthly_quota_period_uses_tehran_subscription_anniversary() -> None:
    start = datetime(2026, 1, 15, 8, 30, tzinfo=UTC)
    now = datetime(2026, 3, 16, 18, 0, tzinfo=UTC)

    assert monthly_period_start(start, now) == datetime(2026, 3, 15, 8, 30, tzinfo=UTC)


def test_monthly_quota_period_keeps_month_end_anchor_after_short_month() -> None:
    start = datetime(2026, 1, 31, 8, 30, tzinfo=UTC)
    before_month_end = datetime(2026, 3, 30, 18, 0, tzinfo=UTC)
    at_month_end = datetime(2026, 3, 31, 8, 30, tzinfo=UTC)

    assert monthly_period_start(start, before_month_end) == datetime(
        2026, 2, 28, 8, 30, tzinfo=UTC
    )
    assert monthly_period_start(start, at_month_end) == datetime(
        2026, 3, 31, 8, 30, tzinfo=UTC
    )


def test_monthly_credit_expires_on_the_next_tehran_anniversary() -> None:
    start = datetime(2026, 1, 31, 8, 30, tzinfo=UTC)
    subscription_end = datetime(2027, 1, 31, 8, 30, tzinfo=UTC)

    assert monthly_period_end(
        datetime(2026, 2, 28, 8, 30, tzinfo=UTC), subscription_end
    ) == datetime(2026, 3, 31, 8, 30, tzinfo=UTC)


def test_proration_rounds_up() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = datetime(2026, 1, 11, tzinfo=UTC)
    now = datetime(2026, 1, 6, tzinfo=UTC)
    assert prorated_amount(199_001, start, end, now) == 99_501


def test_proration_never_returns_a_negative_charge() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = datetime(2026, 2, 1, tzinfo=UTC)
    assert prorated_amount(199_000, start, end, datetime(2026, 2, 2, tzinfo=UTC)) == 0
