"""Shared public tool results for HTTP history and socket reconnection snapshots."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AssistantToolRun
from app.services import assistant_tools


def payload(run: AssistantToolRun) -> dict[str, Any]:
    preview = run.result_preview or {}
    return {
        "tool_call_id": run.tool_call_id,
        "name": run.tool_name,
        "title": assistant_tools.title(run.tool_name),
        "status": run.status,
        "duration_ms": run.duration_ms,
        "summary": preview.get("summary"),
        "charts": preview.get("charts", []),
        "files": preview.get("files", []),
        "error_code": run.error_code,
    }


async def for_messages(
    session: AsyncSession,
    tenant_id: UUID,
    conversation_id: UUID,
    message_ids: list[UUID],
) -> dict[UUID, list[dict[str, Any]]]:
    if not message_ids:
        return {}
    rows = (
        (
            await session.execute(
                select(AssistantToolRun)
                .where(
                    AssistantToolRun.tenant_id == tenant_id,
                    AssistantToolRun.conversation_id == conversation_id,
                    AssistantToolRun.assistant_message_id.in_(message_ids),
                )
                .order_by(AssistantToolRun.started_at)
            )
        )
        .scalars()
        .all()
    )
    grouped: dict[UUID, list[dict[str, Any]]] = {}
    for run in rows:
        if run.assistant_message_id is not None:
            grouped.setdefault(run.assistant_message_id, []).append(payload(run))
    return grouped
