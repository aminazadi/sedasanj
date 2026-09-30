from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.errors import ApiError
from app.services.commerce import add_months, prorated_amount, subscription_amount


def version(**overrides: object) -> SimpleNamespace:
    values = {
        "monthly_price_toman": 4_999_000,
        "annual_price_toman": 49_990_000,
        "allows_extra_operators": True,
        "extra_operator_monthly_toman": 199_000,
        "extra_operator_annual_toman": 1_990_000,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_annual_price_is_ten_months() -> None:
    plan = version()
    assert plan.annual_price_toman == plan.monthly_price_toman * 10


def test_gold_extra_operator_pricing() -> None:
    assert subscription_amount(version(), "monthly", 2) == (5_397_000, 199_000)
    assert subscription_amount(version(), "annual", 2) == (53_970_000, 1_990_000)


def test_extra_operator_is_rejected_for_other_plans() -> None:
    with pytest.raises(ApiError):
        subscription_amount(version(allows_extra_operators=False), "monthly", 1)


def test_calendar_month_math_clamps_end_of_month() -> None:
    assert add_months(datetime(2026, 1, 31, tzinfo=UTC), 1) == datetime(
        2026, 2, 28, tzinfo=UTC
    )


def test_proration_rounds_up() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = datetime(2026, 1, 11, tzinfo=UTC)
    now = datetime(2026, 1, 6, tzinfo=UTC)
    assert prorated_amount(199_001, start, end, now) == 99_501


def test_proration_never_returns_a_negative_charge() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = datetime(2026, 2, 1, tzinfo=UTC)
    assert prorated_amount(199_000, start, end, datetime(2026, 2, 2, tzinfo=UTC)) == 0
