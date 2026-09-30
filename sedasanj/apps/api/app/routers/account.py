from __future__ import annotations

import csv
import io
import json
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request, Response, status
from sqlalchemy import delete, select, update

from app.deps import OrgAdminDep, TenantSession, UserDep, client_ip
from app.errors import ApiError
from app.models import (
    AnalysisRun,
    AudioObject,
    Call,
    CallInsight,
    CreditReservation,
    Job,
    LedgerEntry,
    Tenant,
    Transcript,
    User,
    Utterance,
    WebhookDelivery,
)
from app.schemas import TenantOut, UserOut
from app.services import audit
from app.services.storage import get_storage

router = APIRouter(prefix="/v1/account", tags=["account"])


@router.get("")
async def get_account(principal: UserDep, session: TenantSession) -> dict[str, Any]:
    assert principal.tenant_id is not None
    tenant = (
        await session.execute(select(Tenant).where(Tenant.id == principal.tenant_id))
    ).scalar_one_or_none()
    user = (
        await session.execute(
            select(User).where(User.id == principal.id, User.tenant_id == principal.tenant_id)
        )
    ).scalar_one_or_none()
    if tenant is None or user is None:
        raise ApiError("not_found", "account not found")
    return {
        "tenant": TenantOut.model_validate(tenant).model_dump(mode="json"),
        "user": UserOut.model_validate(user).model_dump(mode="json"),
    }


@router.get("/export")
async def export_data(
    principal: OrgAdminDep,
    session: TenantSession,
    export_format: Annotated[str, Query(alias="format", pattern="^(json|csv)$")] = "json",
) -> Response:
    """Tenant-initiated export (§13)."""
    rows = (
        await session.execute(
            select(Call, Transcript, CallInsight)
            .outerjoin(
                Transcript,
                (Transcript.call_id == Call.id) & (Transcript.tenant_id == principal.tenant_id),
            )
            .outerjoin(
                CallInsight,
                (CallInsight.call_id == Call.id) & (CallInsight.tenant_id == principal.tenant_id),
            )
            .where(Call.tenant_id == principal.tenant_id)
            .order_by(Call.started_at.desc())
        )
    ).all()

    records: list[dict[str, Any]] = [
        {
            "call_id": str(call.id),
            "asterisk_uniqueid": call.asterisk_uniqueid,
            "caller_number": call.caller_number,
            "dialed_number": call.dialed_number,
            "direction": call.direction,
            "agent_extension": call.agent_extension,
            "started_at": call.started_at.isoformat(),
            "ended_at": call.ended_at.isoformat(),
            "duration_ms": call.duration_ms,
            "billed_seconds": call.billed_seconds,
            "status": call.status,
            "transcript": transcript.full_text if transcript else None,
            "summary": insight.summary if insight else None,
            "sentiment": insight.sentiment if insight else None,
            "intent": insight.intent if insight else None,
            "keywords": ",".join(insight.keywords or []) if insight else None,
            "topics": ",".join(insight.topics or []) if insight else None,
        }
        for call, transcript, insight in rows
    ]

    if export_format == "csv":
        buffer = io.StringIO()
        writer = csv.DictWriter(
            buffer, fieldnames=list(records[0].keys()) if records else ["call_id"]
        )
        writer.writeheader()
        writer.writerows(records)
        return Response(
            content=buffer.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="calls.csv"'},
        )
    return Response(
        content=json.dumps(records, ensure_ascii=False),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="calls.json"'},
    )


@router.delete("/data", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tenant_data(
    request: Request, principal: OrgAdminDep, session: TenantSession
) -> None:
    """Hard delete of call data for this tenant, audio included (§13)."""
    tenant_id = principal.tenant_id
    assert tenant_id is not None
    audio_rows = (
        (await session.execute(select(AudioObject).where(AudioObject.tenant_id == tenant_id)))
        .scalars()
        .all()
    )
    storage = get_storage()
    for audio in audio_rows:
        await storage.delete(audio.object_key)

    # Every statement carries the tenant predicate; RLS is only the second line of defence.
    await session.execute(delete(Utterance).where(Utterance.tenant_id == tenant_id))
    await session.execute(delete(Transcript).where(Transcript.tenant_id == tenant_id))
    await session.execute(delete(CallInsight).where(CallInsight.tenant_id == tenant_id))
    await session.execute(delete(AnalysisRun).where(AnalysisRun.tenant_id == tenant_id))
    await session.execute(delete(WebhookDelivery).where(WebhookDelivery.tenant_id == tenant_id))
    await session.execute(delete(Job).where(Job.tenant_id == tenant_id))
    # Financial history survives as ledger entries; their call pointers are cleared first.
    await session.execute(
        update(LedgerEntry).where(LedgerEntry.tenant_id == tenant_id).values(call_id=None)
    )
    await session.execute(delete(CreditReservation).where(CreditReservation.tenant_id == tenant_id))
    await session.execute(delete(Call).where(Call.tenant_id == tenant_id))
    await session.execute(delete(AudioObject).where(AudioObject.tenant_id == tenant_id))
    await audit.record(
        session,
        actor_type="user",
        actor_id=principal.id,
        tenant_id=principal.tenant_id,
        action="tenant.data_delete",
        payload={"audio_objects": len(audio_rows)},
        ip=client_ip(request),
    )
