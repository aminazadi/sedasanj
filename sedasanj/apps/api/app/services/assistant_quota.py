"""Assistant message quota: one definition of the window and of what counts as used."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AssistantUsage
from app.services.quotas import quota_period_start


def period_start(subscription_start: datetime, now: datetime) -> datetime:
    """Same window as the plan minutes: the subscription anniversary month."""
    return quota_period_start(subscription_start, now)


async def used_messages(session: AsyncSession, tenant_id: UUID, start: datetime) -> int:
    return int(
        (
            await session.execute(
                select(func.count(AssistantUsage.id)).where(
                    AssistantUsage.tenant_id == tenant_id,
                    AssistantUsage.period_start == start,
                    AssistantUsage.status.in_(("reserved", "succeeded")),
                )
            )
        ).scalar_one()
    )
