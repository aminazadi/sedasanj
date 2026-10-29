from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.deps import OperatorDep, TenantSession, client_ip
from app.errors import ApiError
from app.models import AssistantExport
from app.services import audit, ratelimit
from app.services.assistant_export_renderers import MEDIA_TYPES
from app.services.storage import get_storage

router = APIRouter(prefix="/v1/assistant/exports", tags=["assistant"])


@router.get("/{export_id}/download")
async def download_export(
    export_id: UUID,
    request: Request,
    principal: OperatorDep,
    session: TenantSession,
) -> StreamingResponse:
    await ratelimit.enforce(f"assistant-export-download:{principal.id}", 20)
    row = (
        await session.execute(
            select(AssistantExport).where(
                AssistantExport.id == export_id,
                AssistantExport.tenant_id == principal.tenant_id,
            )
        )
    ).scalar_one_or_none()
    if row is not None and row.user_id != principal.id and principal.role != "org_admin":
        raise ApiError("not_found", "فایل پیدا نشد؛ از دستیار خودتان خروجی جدید بگیرید")
    # Purged UUIDs have the same expired response without exposing another tenant's metadata.
    if row is None or row.deleted_at is not None or row.expires_at <= datetime.now(UTC):
        raise ApiError("export_expired", "مهلت دریافت فایل تمام شده؛ از دستیار خروجی جدید بخواهید")
    await audit.record(
        session,
        actor_type="user",
        actor_id=principal.id,
        tenant_id=principal.tenant_id,
        action="assistant.export.download",
        payload={"export_id": str(row.id)},
        ip=client_ip(request),
    )
    return StreamingResponse(
        get_storage().iter_chunks(row.storage_key),
        media_type=MEDIA_TYPES[row.format],
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(row.filename)}",
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Length": str(row.size_bytes),
        },
    )
