from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditEvent


async def record(
    session: AsyncSession,
    *,
    actor_type: str,
    action: str,
    actor_id: UUID | None = None,
    tenant_id: UUID | None = None,
    payload: dict[str, Any] | None = None,
    ip: str | None = None,
) -> None:
    """Append-only trail; every staff mutation goes through here (§13)."""
    session.add(
        AuditEvent(
            actor_type=actor_type,
            actor_id=actor_id,
            tenant_id=tenant_id,
            action=action,
            payload=payload or {},
            ip=ip,
        )
    )
    await session.flush()
