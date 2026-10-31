"""Read API for external systems (CRM, BI) authenticated by a scoped API key.

Only call results and phonebook lookups are exposed here. Nothing in this router touches the
assistant, its conversations, memories or exports; those stay behind the signed-in panel.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import ApiKeySession, CallsReadKeyDep, ContactsReadKeyDep
from app.errors import ApiError
from app.models import Call, CallInsight, Contact, CrmOutcome, OperatorCallScore, SalesInsight
from app.routers.calls import _decode_cursor, _encode_cursor, _parse_date_boundary
from app.services.contacts import phone_key
from app.services.phone_numbers import normalize_call_number

router = APIRouter(prefix="/v1/integration", tags=["integration"])

RECENT_CALLS_LIMIT = 10


class IntegrationSales(BaseModel):
    funnel_stage: str
    outcome: str
    certainty: str
    confidence: float
    product: str | None = None
    next_action: str | None = None
    next_action_due_at: datetime | None = None


class IntegrationCrmOutcome(BaseModel):
    external_lead_id: str
    outcome: str
    funnel_stage: str | None = None
    amount: int | None = None
    currency: str | None = None
    occurred_at: datetime


class IntegrationCall(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    asterisk_uniqueid: str
    external_reference: str | None = None
    campaign_id: str | None = None
    source: str | None = None
    caller_number: str | None = None
    dialed_number: str | None = None
    direction: str | None = None
    agent_extension: str | None = None
    call_type: str
    started_at: datetime
    ended_at: datetime
    duration_ms: int
    status: str
    summary: str | None = None
    keywords: list[str] = []
    sentiment: str | None = None
    intent: str | None = None
    topics: list[str] = []
    action_items: Any | None = None
    sales: IntegrationSales | None = None
    operator_score: float | None = None
    crm_outcome: IntegrationCrmOutcome | None = None


class IntegrationCallPage(BaseModel):
    items: list[IntegrationCall]
    next_cursor: str | None = None


class IntegrationContact(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    phone_number: str
    name: str
    company: str | None = None
    email: str | None = None
    province: str | None = None
    city: str | None = None


class ContactLookup(BaseModel):
    phone_number: str
    contact: IntegrationContact | None = None
    recent_calls: list[IntegrationCall]
    last_crm_outcome: IntegrationCrmOutcome | None = None


async def _build_calls(
    session: AsyncSession, tenant_id: UUID, rows: list[tuple[Call, CallInsight | None]]
) -> list[IntegrationCall]:
    """Attach sales, operator score and CRM outcome to calls with one query per table."""
    ids = [call.id for call, _ in rows]
    sales: dict[UUID, SalesInsight] = {}
    scores: dict[UUID, float] = {}
    outcomes: dict[UUID, CrmOutcome] = {}
    if ids:
        for row in (
            await session.execute(
                select(SalesInsight).where(
                    SalesInsight.tenant_id == tenant_id, SalesInsight.call_id.in_(ids)
                )
            )
        ).scalars():
            sales[row.call_id] = row
        for score in (
            await session.execute(
                select(OperatorCallScore)
                .where(
                    OperatorCallScore.tenant_id == tenant_id,
                    OperatorCallScore.call_id.in_(ids),
                    OperatorCallScore.total_score.is_not(None),
                )
                .order_by(OperatorCallScore.created_at)
            )
        ).scalars():
            if score.total_score is not None:
                scores[score.call_id] = float(score.total_score)
        for outcome in (
            await session.execute(
                select(CrmOutcome)
                .where(CrmOutcome.tenant_id == tenant_id, CrmOutcome.call_id.in_(ids))
                .order_by(CrmOutcome.occurred_at)
            )
        ).scalars():
            if outcome.call_id is not None:
                outcomes[outcome.call_id] = outcome

    items: list[IntegrationCall] = []
    for call, insight in rows:
        sales_row = sales.get(call.id)
        outcome_row = outcomes.get(call.id)
        items.append(
            IntegrationCall(
                id=call.id,
                asterisk_uniqueid=call.asterisk_uniqueid,
                external_reference=call.external_reference,
                campaign_id=call.campaign_id,
                source=call.source,
                caller_number=call.caller_number,
                dialed_number=call.dialed_number,
                direction=call.direction,
                agent_extension=call.agent_extension,
                call_type=call.call_type,
                started_at=call.started_at,
                ended_at=call.ended_at,
                duration_ms=call.duration_ms,
                status=call.status,
                summary=insight.summary if insight else None,
                keywords=list(insight.keywords or []) if insight else [],
                sentiment=insight.sentiment if insight else None,
                intent=insight.intent if insight else None,
                topics=list(insight.topics or []) if insight else [],
                action_items=insight.action_items if insight else None,
                sales=(
                    IntegrationSales(
                        funnel_stage=sales_row.funnel_stage,
                        outcome=sales_row.outcome,
                        certainty=sales_row.certainty,
                        confidence=float(sales_row.confidence),
                        product=sales_row.product,
                        next_action=sales_row.next_action,
                        next_action_due_at=sales_row.next_action_due_at,
                    )
                    if sales_row
                    else None
                ),
                operator_score=scores.get(call.id),
                crm_outcome=_outcome_out(outcome_row) if outcome_row else None,
            )
        )
    return items


def _outcome_out(row: CrmOutcome) -> IntegrationCrmOutcome:
    return IntegrationCrmOutcome(
        external_lead_id=row.external_lead_id,
        outcome=row.outcome,
        funnel_stage=row.funnel_stage,
        amount=row.amount,
        currency=row.currency,
        occurred_at=row.occurred_at,
    )


def _calls_stmt(tenant_id: UUID) -> Any:
    return (
        select(Call, CallInsight)
        .outerjoin(CallInsight, CallInsight.call_id == Call.id)
        .where(Call.tenant_id == tenant_id)
        .order_by(Call.started_at.desc(), Call.id.desc())
    )


@router.get("/calls", response_model=IntegrationCallPage)
async def list_calls(
    principal: CallsReadKeyDep,
    session: ApiKeySession,
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    from_: Annotated[str | None, Query(alias="from")] = None,
    to: Annotated[str | None, Query()] = None,
    external_reference: Annotated[str | None, Query(max_length=200)] = None,
    number: Annotated[str | None, Query(max_length=40)] = None,
    campaign_id: Annotated[str | None, Query(max_length=200)] = None,
    source: Annotated[str | None, Query(max_length=200)] = None,
    status: Annotated[str | None, Query(max_length=40)] = None,
) -> IntegrationCallPage:
    assert principal.tenant_id is not None
    stmt = _calls_stmt(principal.tenant_id)
    start = _parse_date_boundary(from_, end=False)
    end = _parse_date_boundary(to, end=True)
    if start is not None:
        stmt = stmt.where(Call.started_at >= start)
    if end is not None:
        stmt = stmt.where(Call.started_at <= end)
    if external_reference:
        stmt = stmt.where(Call.external_reference == external_reference)
    if campaign_id:
        stmt = stmt.where(Call.campaign_id == campaign_id)
    if source:
        stmt = stmt.where(Call.source == source)
    if status:
        stmt = stmt.where(Call.status == status)
    if number:
        key = normalize_call_number(number)
        if not key:
            raise ApiError("invalid_request", "number must contain digits")
        stmt = stmt.where(or_(Call.caller_number == key, Call.dialed_number == key))
    if cursor:
        started_at, call_id = _decode_cursor(cursor)
        stmt = stmt.where(
            or_(
                Call.started_at < started_at,
                and_(Call.started_at == started_at, Call.id < call_id),
            )
        )
    fetched = (await session.execute(stmt.limit(limit + 1))).all()
    rows = [(call, insight) for call, insight in fetched]
    has_more = len(rows) > limit
    rows = rows[:limit]
    items = await _build_calls(session, principal.tenant_id, rows)
    next_cursor = _encode_cursor(rows[-1][0].started_at, rows[-1][0].id) if has_more else None
    return IntegrationCallPage(items=items, next_cursor=next_cursor)


@router.get("/calls/by-external/{external_reference}", response_model=IntegrationCall)
async def call_by_external_reference(
    external_reference: str, principal: CallsReadKeyDep, session: ApiKeySession
) -> IntegrationCall:
    """Find the call your system registered through `external_reference` at upload time."""
    assert principal.tenant_id is not None
    rows = (
        await session.execute(
            _calls_stmt(principal.tenant_id)
            .where(Call.external_reference == external_reference)
            .limit(1)
        )
    ).all()
    if not rows:
        raise ApiError("not_found", "no call has this external_reference")
    return (await _build_calls(session, principal.tenant_id, [(rows[0][0], rows[0][1])]))[0]


@router.get("/calls/{call_id}", response_model=IntegrationCall)
async def get_call(
    call_id: UUID, principal: CallsReadKeyDep, session: ApiKeySession
) -> IntegrationCall:
    assert principal.tenant_id is not None
    rows = (await session.execute(_calls_stmt(principal.tenant_id).where(Call.id == call_id))).all()
    if not rows:
        raise ApiError("not_found", "call not found")
    return (await _build_calls(session, principal.tenant_id, [(rows[0][0], rows[0][1])]))[0]


@router.get("/contacts/lookup", response_model=ContactLookup)
async def lookup_contact(
    principal: ContactsReadKeyDep,
    session: ApiKeySession,
    phone: Annotated[str, Query(min_length=3, max_length=40)],
) -> ContactLookup:
    """Phonebook entry, latest calls and latest CRM outcome for one phone number."""
    assert principal.tenant_id is not None
    key = phone_key(phone)
    if key is None:
        raise ApiError("invalid_request", "phone is not a usable phone number")
    contact = (
        await session.execute(
            select(Contact).where(
                Contact.tenant_id == principal.tenant_id, Contact.phone_number == key
            )
        )
    ).scalar_one_or_none()
    rows = (
        await session.execute(
            _calls_stmt(principal.tenant_id)
            .where(or_(Call.caller_number == key, Call.dialed_number == key))
            .limit(RECENT_CALLS_LIMIT)
        )
    ).all()
    calls = await _build_calls(session, principal.tenant_id, [(c, i) for c, i in rows])
    latest = max(
        (call.crm_outcome for call in calls if call.crm_outcome is not None),
        key=lambda outcome: outcome.occurred_at,
        default=None,
    )
    return ContactLookup(
        phone_number=key,
        contact=IntegrationContact.model_validate(contact) if contact else None,
        recent_calls=calls,
        last_crm_outcome=latest,
    )
