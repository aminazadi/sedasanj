"""Shared predicates that keep colleague-to-colleague (internal) calls out of customer metrics."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import ColumnElement, Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Call, KpiConfiguration

INTERNAL_DIRECTION = "internal"


def not_internal_clause() -> ColumnElement[bool]:
    """True for customer calls; a NULL direction counts as a customer call."""
    return or_(Call.direction.is_(None), Call.direction != INTERNAL_DIRECTION)


def exclude_internal(statement: Select) -> Select:  # type: ignore[type-arg]
    return statement.where(not_internal_clause())


async def internal_hidden(session: AsyncSession, tenant_id: UUID) -> bool:
    """True unless the tenant's active KPI settings opt internal calls into customer metrics."""
    settings = (
        await session.execute(
            select(KpiConfiguration.settings)
            .where(KpiConfiguration.tenant_id == tenant_id, KpiConfiguration.active.is_(True))
            .order_by(KpiConfiguration.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return not bool((settings or {}).get("include_internal_calls", False))
