"""Preview and apply conservative PBX ownership repairs."""

from datetime import UTC, datetime
from hashlib import sha256
from typing import TypedDict
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Call, CallOperatorAssignment, PbxExtension
from app.services import call_parties

_AUTOMATIC_SOURCES = {
    "ingest_exact_extension",
    "missed_call_ingest_exact_extension",
    "scoring_identity_match",
    "pbx_party_ingest",
    "pbx_party_review",
}


class RepairPreview(TypedDict):
    call_id: UUID
    started_at: datetime
    direction: str | None
    proposed_direction: str | None
    operators: list[UUID]
    proposed_operators: list[UUID]
    status: str
    token: str | None


async def preview(
    session: AsyncSession, call: Call
) -> tuple[RepairPreview, list[CallOperatorAssignment], call_parties.CallParties]:
    current = list(
        (
            await session.scalars(
                select(CallOperatorAssignment)
                .where(
                    CallOperatorAssignment.tenant_id == call.tenant_id,
                    CallOperatorAssignment.call_id == call.id,
                    CallOperatorAssignment.superseded_at.is_(None),
                )
                .order_by(CallOperatorAssignment.id)
            )
        ).all()
    )
    parties = await call_parties.resolve(
        session,
        call.tenant_id,
        caller=call.raw_caller_number or call.caller_number,
        dialed=call.raw_dialed_number or call.dialed_number,
        direction=call.direction,
        agent=call.agent_extension,
        caller_extension=call.caller_extension,
        dialed_extension=call.dialed_extension,
        evidence=call.pbx_evidence,
        call_type=call.call_type,
    )
    existing = {row.operator_id: (row.agent_extension, row.party_role) for row in current}
    legacy_exact = call.direction in {"inbound", "outbound"} and any(
        row.assignment_source in {"ingest_exact_extension", "missed_call_ingest_exact_extension"}
        and row.agent_extension == call.agent_extension
        for row in current
    )
    eligible = (
        call.pbx_evidence in {"cdr", "direct"} or call.call_type == "voicemail" or legacy_exact
    )
    proposed = (
        await call_parties.assignments_for(session, call.tenant_id, parties, call.call_type)
        if eligible
        else {}
    )
    manual = any(row.assignment_source not in _AUTOMATIC_SOURCES for row in current)
    # A partial match or a changed extension owner needs independent historical evidence.
    previous_owners = {row.agent_extension: row.operator_id for row in current}
    candidates = parties.operator_candidates(call.call_type)
    contemporaneous = {}
    if any(extension not in previous_owners for extension, _ in proposed.values()):
        contemporaneous = dict(
            (
                await session.execute(
                    select(PbxExtension.extension, PbxExtension.user_id).where(
                        PbxExtension.tenant_id == call.tenant_id,
                        PbxExtension.extension.in_(candidates),
                        PbxExtension.active.is_(True),
                        PbxExtension.owner_linked_at <= call.started_at,
                    )
                )
            ).all()
        )
    changed_owner = any(
        previous_owners.get(extension, contemporaneous.get(extension)) != operator_id
        for operator_id, (extension, _) in proposed.items()
    )
    complete = bool(candidates) and set(candidates) == {value[0] for value in proposed.values()}
    status = "ambiguous"
    token = None
    if eligible and complete and not manual and not changed_owner:
        status = "unchanged"
        if existing != proposed or call.direction != parties.direction:
            status = "review"
            token = sha256(
                repr(
                    (
                        call.id,
                        call.direction,
                        parties,
                        current_signature(current),
                        sorted(proposed.items()),
                    )
                ).encode()
            ).hexdigest()
    return (
        {
            "call_id": call.id,
            "started_at": call.started_at,
            "direction": call.direction,
            "proposed_direction": parties.direction if token else call.direction,
            "operators": list(existing),
            "proposed_operators": list(proposed) if token else list(existing),
            "status": status,
            "token": token,
        },
        current,
        parties,
    )


def current_signature(rows: list[CallOperatorAssignment]) -> list[tuple[object, ...]]:
    return [
        (row.id, row.operator_id, row.agent_extension, row.party_role, row.assignment_source)
        for row in rows
    ]


async def apply(session: AsyncSession, call: Call, token: str) -> RepairPreview | None:
    review, current, parties = await preview(session, call)
    if review["token"] != token:
        return None
    now = datetime.now(UTC)
    for row in current:
        row.superseded_at = now
    call.direction = parties.direction
    call.caller_extension = parties.caller_extension
    call.dialed_extension = parties.dialed_extension
    call.agent_extension = parties.agent_extension
    await session.flush()
    await call_parties.assign(session, call, parties, source="pbx_party_review")
    await session.flush()
    return review
