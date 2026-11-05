"""Resolve PBX parties and snapshot operator ownership when a call is accepted."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Call, CallOperatorAssignment, PbxExtension, Tenant, User
from app.services.extensions import extension_key, known_extensions, lock_inventory


@dataclass(frozen=True)
class CallParties:
    direction: str | None
    caller_extension: str | None
    dialed_extension: str | None
    agent_extension: str | None
    evidence: str | None

    def operator_candidates(self, call_type: str) -> dict[str, str]:
        if self.direction == "internal":
            candidates: dict[str, str] = {}
            if self.caller_extension:
                candidates[self.caller_extension] = "caller"
            if self.dialed_extension:
                role = "callee" if call_type == "answered" else "unanswered_destination"
                if self.dialed_extension in candidates:
                    role = (
                        "both" if call_type == "answered" else "caller_and_unanswered_destination"
                    )
                candidates[self.dialed_extension] = role
            return candidates
        if self.agent_extension:
            role = "agent"
            if self.direction == "outbound":
                role = "caller"
            elif call_type == "voicemail":
                role = "mailbox"
            elif call_type != "answered":
                role = "unanswered_destination"
            return {self.agent_extension: role}
        return {}


def classify(
    *,
    known: set[str],
    caller: str | None,
    dialed: str,
    direction: str | None,
    agent: str | None,
    caller_extension: str | None = None,
    dialed_extension: str | None = None,
    evidence: str | None = None,
    call_type: str = "answered",
) -> CallParties:
    def verified(value: str | None) -> str | None:
        key = extension_key(value)
        return key if key in known else None

    origin = verified(caller_extension)
    destination = verified(dialed_extension)
    if evidence == "ambiguous":
        return CallParties(direction, origin, destination, None, evidence)
    if direction == "internal":
        if evidence is None:
            origin = verified(caller)
            destination = verified(dialed)
        if not (origin and destination):
            if call_type != "answered" and evidence == "direct":
                return CallParties(None, origin, destination, destination, evidence)
            return CallParties(direction, origin, destination, None, evidence)
        return CallParties("internal", origin, destination, destination, evidence)
    if origin and destination and direction is None:
        return CallParties("internal", origin, destination, destination, evidence)
    if call_type == "voicemail":
        destination = verified(dialed)
        return CallParties(direction, origin, destination, destination, evidence)
    if direction == "outbound":
        agent = origin or (agent if evidence is None else None)
    elif call_type != "answered":
        agent = destination or (agent if evidence is None else None)
    return CallParties(
        direction,
        origin,
        destination,
        verified(agent) if evidence else extension_key(agent),
        evidence,
    )


async def resolve(
    session: AsyncSession, tenant_id: UUID, *, host_uuid: UUID | None = None, **metadata: str | None
) -> CallParties:
    await lock_inventory(session, tenant_id, shared=True)
    if host_uuid is not None:
        bound_host = await session.scalar(
            select(Tenant.pbx_host_uuid).where(Tenant.id == tenant_id)
        )
        if bound_host is not None and bound_host != host_uuid:
            return CallParties(None, None, None, None, "ambiguous")
    return classify(
        known=await known_extensions(session, tenant_id),
        caller=metadata.get("caller"),
        dialed=metadata.get("dialed") or "",
        direction=metadata.get("direction"),
        agent=metadata.get("agent"),
        caller_extension=metadata.get("caller_extension"),
        dialed_extension=metadata.get("dialed_extension"),
        evidence=metadata.get("evidence"),
        call_type=metadata.get("call_type") or "answered",
    )


async def assignments_for(
    session: AsyncSession, tenant_id: UUID, parties: CallParties, call_type: str
) -> dict[UUID, tuple[str, str]]:
    candidates = parties.operator_candidates(call_type)
    if not candidates:
        return {}
    inventory = {
        row.extension: row
        for row in (
            await session.scalars(
                select(PbxExtension).where(
                    PbxExtension.tenant_id == tenant_id, PbxExtension.extension.in_(candidates)
                )
            )
        ).all()
    }
    operators = (
        await session.scalars(
            select(User).where(User.tenant_id == tenant_id, User.role == "operator")
        )
    ).all()
    result: dict[UUID, tuple[str, str]] = {}
    for extension, role in candidates.items():
        entry = inventory.get(extension)
        if entry is not None:
            if not entry.active or entry.user_id is None:
                continue
            matches = [user for user in operators if user.id == entry.user_id]
        else:
            matches = [user for user in operators if extension_key(user.extension) == extension]
        if len(matches) != 1:
            continue
        operator_id = matches[0].id
        if operator_id in result:
            role = "both" if call_type == "answered" else "caller_and_unanswered_destination"
        result[operator_id] = (extension, role)
    return result


async def assign(
    session: AsyncSession, call: Call, parties: CallParties, *, source: str = "pbx_party_ingest"
) -> None:
    for operator_id, (extension, role) in (
        await assignments_for(session, call.tenant_id, parties, call.call_type)
    ).items():
        session.add(
            CallOperatorAssignment(
                tenant_id=call.tenant_id,
                call_id=call.id,
                operator_id=operator_id,
                agent_extension=extension,
                party_role=role,
                assignment_source=source,
            )
        )
