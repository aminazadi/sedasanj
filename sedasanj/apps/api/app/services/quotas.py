from __future__ import annotations

from calendar import monthrange
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

TEHRAN = ZoneInfo("Asia/Tehran")


def monthly_period_start(subscription_start: datetime, now: datetime) -> datetime:
    local_start = subscription_start.astimezone(TEHRAN)
    local_now = now.astimezone(TEHRAN)
    months = (local_now.year - local_start.year) * 12 + local_now.month - local_start.month
    while months >= 0:
        year = local_start.year + (local_start.month - 1 + months) // 12
        month = (local_start.month - 1 + months) % 12 + 1
        day = _anniversary_day(local_start, year, month)
        candidate = local_start.replace(year=year, month=month, day=day)
        if candidate <= local_now:
            return candidate.astimezone(UTC)
        months -= 1
    return local_start.astimezone(UTC)


def monthly_period_end(period_start: datetime, subscription_end: datetime) -> datetime:
    local_start = period_start.astimezone(TEHRAN)
    next_month = local_start.month % 12 + 1
    next_year = local_start.year + (1 if local_start.month == 12 else 0)
    day = _anniversary_day(local_start, next_year, next_month)
    local_end = local_start.replace(year=next_year, month=next_month, day=day)
    return min(local_end.astimezone(UTC), subscription_end)


def _anniversary_day(anchor: datetime, year: int, month: int) -> int:
    if anchor.day == monthrange(anchor.year, anchor.month)[1]:
        return monthrange(year, month)[1]
    return min(anchor.day, monthrange(year, month)[1])


def calendar_month_start(now: datetime) -> datetime:
    return (
        now.astimezone(TEHRAN)
        .replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        .astimezone(UTC)
    )


def quota_period_start(subscription_start: datetime, now: datetime) -> datetime:
    """Start of the monthly quota window; minutes and assistant messages share it.

    A subscription that has not started yet reports its own start instead of a past window.
    """
    if subscription_start > now:
        return subscription_start
    return monthly_period_start(subscription_start, now)
