from datetime import UTC, datetime

import pytest

from app.errors import ApiError
from app.routers.calls import _parse_date_boundary


def test_date_only_filters_cover_the_full_tehran_day() -> None:
    assert _parse_date_boundary("2026-10-02", end=False) == datetime(
        2026, 10, 1, 20, 30, tzinfo=UTC
    )
    assert _parse_date_boundary("2026-10-02", end=True) == datetime(
        2026, 10, 2, 20, 29, 59, 999999, tzinfo=UTC
    )


def test_date_filters_preserve_historical_tehran_daylight_saving() -> None:
    assert _parse_date_boundary("2021-07-01", end=False) == datetime(
        2021, 6, 30, 19, 30, tzinfo=UTC
    )


def test_date_filters_accept_aware_datetimes() -> None:
    assert _parse_date_boundary("2026-10-02T12:00:00Z", end=False) == datetime(
        2026, 10, 2, 12, 0, tzinfo=UTC
    )


def test_invalid_date_filter_is_rejected() -> None:
    with pytest.raises(ApiError):
        _parse_date_boundary("not-a-date", end=False)
