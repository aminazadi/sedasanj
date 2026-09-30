from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.deps import ApiKeyDep, ApiKeySession, OrgAdminDep, TenantSession, UserDep, client_ip
from app.errors import ApiError
from app.models import (
    Call,
    CallInsight,
    CallOperatorAssignment,
    CrmOutcome,
    FollowUpTask,
    KpiConfiguration,
    KpiGoal,
    OperatorCallScore,
    SalesInsight,
    Team,
    TeamMembership,
    User,
    Utterance,
)
from app.services import audit, operator_scope

router = APIRouter(prefix="/v1", tags=["sales KPI"])

DEFAULT_SETTINGS: dict[str, Any] = {
    "follow_up_sla_hours": 24,
    "minimum_sample_size": 5,
    "probable_confidence_threshold": 0.65,
    "hot_opportunity_threshold": 0.8,
    "operator_team_comparison_visible": True,
    "taxonomy_version": 1,
    "funnel_stages": [
        "effective",
        "qualified",
        "interested",
        "follow_up",
        "proposal",
        "won",
        "lost",
    ],
    "objection_taxonomy": ["price", "trust", "timing", "competitor", "no_need", "other"],
}


class KpiSettingsIn(BaseModel):
    follow_up_sla_hours: int = Field(ge=1, le=720)
    minimum_sample_size: int = Field(ge=1, le=1000)
    probable_confidence_threshold: float = Field(ge=0, le=1)
    hot_opportunity_threshold: float = Field(ge=0, le=1)
    operator_team_comparison_visible: bool = True
    taxonomy_version: int = Field(ge=1)
    funnel_stages: list[str] = Field(min_length=1, max_length=20)
    objection_taxonomy: list[str] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def valid_taxonomies(self) -> KpiSettingsIn:
        allowed_stages = set(DEFAULT_SETTINGS["funnel_stages"])
        required_stages = {"effective", "qualified", "won", "lost"}
        if len(self.funnel_stages) != len(set(self.funnel_stages)):
            raise ValueError("funnel_stages must be unique")
        if not set(self.funnel_stages).issubset(allowed_stages):
            raise ValueError("funnel_stages contains unsupported values")
        if not required_stages.issubset(self.funnel_stages):
            raise ValueError("funnel_stages is missing required values")
        normalized = [value.strip().lower() for value in self.objection_taxonomy]
        if any(not value for value in normalized) or len(normalized) != len(set(normalized)):
            raise ValueError("objection_taxonomy must contain unique non-empty values")
        self.objection_taxonomy = normalized
        return self


class TeamIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)


class MembershipIn(BaseModel):
    operator_id: UUID
    valid_from: datetime = Field(default_factory=lambda: datetime.now(UTC))


class GoalIn(BaseModel):
    metric: Literal["conversion_rate", "quality_score", "follow_up_sla_rate"]
    target_value: float = Field(gt=0)
    team_id: UUID | None = None
    valid_from: datetime
    valid_to: datetime

    @model_validator(mode="after")
    def valid_window(self) -> GoalIn:
        if self.valid_to <= self.valid_from:
            raise ValueError("valid_to must be after valid_from")
        return self


class CrmOutcomeIn(BaseModel):
    external_lead_id: str = Field(min_length=1, max_length=200)
    call_id: UUID | None = None
    external_call_reference: str | None = Field(default=None, max_length=200)
    customer_id: str | None = Field(default=None, max_length=200)
    campaign_id: str | None = Field(default=None, max_length=200)
    source: str | None = Field(default=None, max_length=200)
    channel: str | None = Field(default=None, max_length=100)
    owner_reference: str | None = Field(default=None, max_length=200)
    funnel_stage: str | None = Field(default=None, max_length=100)
    outcome: Literal["won", "lost", "follow_up", "interested", "not_qualified", "unknown"]
    amount: int | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=8)
    product: str | None = Field(default=None, max_length=200)
    occurred_at: datetime


async def _settings(session: Any, tenant_id: UUID) -> tuple[int, dict[str, Any]]:
    row = (
        await session.execute(
            select(KpiConfiguration)
            .where(KpiConfiguration.tenant_id == tenant_id, KpiConfiguration.active.is_(True))
            .order_by(KpiConfiguration.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return (
        (row.version, {**DEFAULT_SETTINGS, **row.settings}) if row else (0, DEFAULT_SETTINGS.copy())
    )


@router.get("/kpi/settings")
async def get_kpi_settings(principal: OrgAdminDep, session: TenantSession) -> dict[str, Any]:
    assert principal.tenant_id is not None
    version, settings = await _settings(session, principal.tenant_id)
    return {"version": version, "settings": settings}


@router.put("/kpi/settings")
async def put_kpi_settings(
    payload: KpiSettingsIn, request: Request, principal: OrgAdminDep, session: TenantSession
) -> dict[str, Any]:
    assert principal.tenant_id is not None
    version, _ = await _settings(session, principal.tenant_id)
    await session.execute(
        update(KpiConfiguration)
        .where(KpiConfiguration.tenant_id == principal.tenant_id, KpiConfiguration.active.is_(True))
        .values(active=False)
    )
    row = KpiConfiguration(
        tenant_id=principal.tenant_id,
        version=version + 1,
        settings=payload.model_dump(),
        active=True,
        created_by=principal.id,
    )
    session.add(row)
    await audit.record(
        session,
        actor_type="user",
        actor_id=principal.id,
        tenant_id=principal.tenant_id,
        action="kpi.settings_update",
        payload={"version": version + 1},
        ip=client_ip(request),
    )
    return {"version": version + 1, "settings": row.settings}


@router.get("/kpi/teams")
async def list_teams(principal: OrgAdminDep, session: TenantSession) -> list[dict[str, Any]]:
    rows = (
        (
            await session.execute(
                select(Team).where(Team.tenant_id == principal.tenant_id).order_by(Team.name)
            )
        )
        .scalars()
        .all()
    )
    memberships = (
        await session.execute(
            select(TeamMembership, User)
            .join(User, User.id == TeamMembership.operator_id)
            .where(
                TeamMembership.tenant_id == principal.tenant_id, TeamMembership.valid_to.is_(None)
            )
        )
    ).all()
    members: dict[UUID, list[dict[str, Any]]] = defaultdict(list)
    for membership, user in memberships:
        members[membership.team_id].append(
            {
                "id": str(user.id),
                "name": user.display_name or user.email,
                "valid_from": membership.valid_from,
            }
        )
    return [
        {"id": str(row.id), "name": row.name, "active": row.active, "members": members[row.id]}
        for row in rows
    ]


@router.post("/kpi/teams", status_code=status.HTTP_201_CREATED)
async def create_team(
    payload: TeamIn, request: Request, principal: OrgAdminDep, session: TenantSession
) -> dict[str, Any]:
    row = Team(tenant_id=principal.tenant_id, name=payload.name.strip())
    session.add(row)
    await session.flush()
    await audit.record(
        session,
        actor_type="user",
        actor_id=principal.id,
        tenant_id=principal.tenant_id,
        action="kpi.team_create",
        payload={"team_id": str(row.id)},
        ip=client_ip(request),
    )
    return {"id": str(row.id), "name": row.name, "active": row.active, "members": []}


@router.post("/kpi/teams/{team_id}/members", status_code=status.HTTP_201_CREATED)
async def assign_member(
    team_id: UUID,
    payload: MembershipIn,
    request: Request,
    principal: OrgAdminDep,
    session: TenantSession,
) -> dict[str, Any]:
    team = await session.get(Team, team_id)
    user = await session.get(User, payload.operator_id)
    if (
        team is None
        or team.tenant_id != principal.tenant_id
        or user is None
        or user.tenant_id != principal.tenant_id
        or user.role != "operator"
    ):
        raise ApiError("not_found", "team or operator not found")
    conflicting_membership = (
        await session.execute(
            select(TeamMembership.id)
            .where(
                TeamMembership.tenant_id == principal.tenant_id,
                TeamMembership.operator_id == user.id,
                TeamMembership.valid_from >= payload.valid_from,
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if conflicting_membership is not None:
        raise ApiError("conflict", "membership start must follow existing membership history")
    await session.execute(
        update(TeamMembership)
        .where(
            TeamMembership.tenant_id == principal.tenant_id,
            TeamMembership.operator_id == user.id,
            TeamMembership.valid_to.is_(None),
        )
        .values(valid_to=payload.valid_from)
    )
    row = TeamMembership(
        tenant_id=principal.tenant_id,
        team_id=team.id,
        operator_id=user.id,
        valid_from=payload.valid_from,
    )
    session.add(row)
    await audit.record(
        session,
        actor_type="user",
        actor_id=principal.id,
        tenant_id=principal.tenant_id,
        action="kpi.team_member_assign",
        payload={"team_id": str(team.id), "operator_id": str(user.id)},
        ip=client_ip(request),
    )
    return {"team_id": str(team.id), "operator_id": str(user.id), "valid_from": payload.valid_from}


@router.post("/kpi/goals", status_code=status.HTTP_201_CREATED)
async def create_goal(
    payload: GoalIn, request: Request, principal: OrgAdminDep, session: TenantSession
) -> dict[str, Any]:
    if payload.team_id is not None:
        team = await session.get(Team, payload.team_id)
        if team is None or team.tenant_id != principal.tenant_id:
            raise ApiError("not_found", "team not found")
    overlap = (
        await session.execute(
            select(KpiGoal.id).where(
                KpiGoal.tenant_id == principal.tenant_id,
                KpiGoal.metric == payload.metric,
                KpiGoal.team_id == payload.team_id
                if payload.team_id
                else KpiGoal.team_id.is_(None),
                KpiGoal.valid_from < payload.valid_to,
                KpiGoal.valid_to > payload.valid_from,
            )
        )
    ).scalar_one_or_none()
    if overlap is not None:
        raise ApiError("conflict", "an overlapping goal already exists")
    row = KpiGoal(
        tenant_id=principal.tenant_id,
        team_id=payload.team_id,
        metric=payload.metric,
        target_value=payload.target_value,
        valid_from=payload.valid_from,
        valid_to=payload.valid_to,
        created_by=principal.id,
    )
    session.add(row)
    await session.flush()
    await audit.record(
        session,
        actor_type="user",
        actor_id=principal.id,
        tenant_id=principal.tenant_id,
        action="kpi.goal_create",
        payload={"goal_id": str(row.id), "metric": row.metric},
        ip=client_ip(request),
    )
    return {"id": str(row.id), **payload.model_dump()}


@router.get("/kpi/goals")
async def list_goals(
    principal: OrgAdminDep,
    session: TenantSession,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> dict[str, Any]:
    base = select(KpiGoal).where(KpiGoal.tenant_id == principal.tenant_id)
    total = int(
        (await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    )
    rows = (
        (
            await session.execute(
                base
                .order_by(KpiGoal.valid_from.desc())
                .offset(offset)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    items = [
        {
            "id": str(row.id),
            "team_id": str(row.team_id) if row.team_id else None,
            "metric": row.metric,
            "target_value": row.target_value,
            "valid_from": row.valid_from,
            "valid_to": row.valid_to,
        }
        for row in rows
    ]
    return {
        "items": items,
        "total": total,
        "next_cursor": str(offset + limit) if offset + len(items) < total else None,
    }


@router.post("/crm/outcomes")
async def upsert_crm_outcome(
    payload: CrmOutcomeIn, principal: ApiKeyDep, session: ApiKeySession
) -> dict[str, Any]:
    tenant_id = principal.tenant_id
    assert tenant_id is not None
    call = None
    if payload.call_id is not None:
        call = await session.get(Call, payload.call_id)
        if call is None or call.tenant_id != tenant_id:
            raise ApiError("not_found", "call not found")
    elif payload.external_call_reference:
        call = (
            await session.execute(
                select(Call).where(
                    Call.tenant_id == tenant_id,
                    or_(
                        Call.external_reference == payload.external_call_reference,
                        Call.asterisk_uniqueid == payload.external_call_reference,
                    ),
                )
            )
        ).scalar_one_or_none()
    values = payload.model_dump(exclude={"call_id"})
    values.update(
        tenant_id=tenant_id,
        call_id=call.id if call else None,
        payload=payload.model_dump(mode="json"),
        updated_at=datetime.now(UTC),
    )
    insert_stmt = pg_insert(CrmOutcome).values(**values)
    result = (
        await session.execute(
            insert_stmt.on_conflict_do_update(
                constraint="crm_outcomes_tenant_lead_key",
                set_={
                    key: getattr(insert_stmt.excluded, key) for key in values if key != "tenant_id"
                },
                where=insert_stmt.excluded.occurred_at >= CrmOutcome.occurred_at,
            ).returning(CrmOutcome.id, CrmOutcome.call_id)
        )
    ).one_or_none()
    if result is None:
        existing = (
            await session.execute(
                select(CrmOutcome.id, CrmOutcome.call_id).where(
                    CrmOutcome.tenant_id == tenant_id,
                    CrmOutcome.external_lead_id == payload.external_lead_id,
                )
            )
        ).one()
        return {
            "id": str(existing.id),
            "status": "ignored_stale",
            "call_id": str(existing.call_id) if existing.call_id else None,
        }
    return {
        "id": str(result.id),
        "status": "upserted",
        "call_id": str(result.call_id) if result.call_id else None,
    }


def _rate(numerator: int | float, denominator: int | float) -> dict[str, Any]:
    return {
        "value": round(float(numerator) * 100 / denominator, 1) if denominator else None,
        "numerator": numerator,
        "denominator": denominator,
    }


def _rate_with_change(
    numerator: int | float,
    denominator: int | float,
    previous_numerator: int | float,
    previous_denominator: int | float,
) -> dict[str, Any]:
    current = _rate(numerator, denominator)
    previous = _rate(previous_numerator, previous_denominator)
    current["previous_value"] = previous["value"]
    current["change"] = (
        round(float(current["value"]) - float(previous["value"]), 1)
        if current["value"] is not None and previous["value"] is not None
        else None
    )
    return current


def _is_opportunity(insight: CallInsight | None, sales: SalesInsight | None) -> bool:
    if sales is None or sales.outcome == "not_qualified":
        return False
    return bool(
        (insight and insight.intent in {"sales_inquiry", "consultation"})
        or sales.funnel_stage not in {"all_calls", "effective", "unknown"}
    )


def _has_known_ai_outcome(sales: SalesInsight | None, probable_threshold: float) -> bool:
    if sales is None or sales.outcome == "unknown" or sales.certainty == "unknown":
        return False
    return sales.certainty == "explicit" or sales.confidence >= probable_threshold


def _funnel_rows(
    rows: Any,
    stages: list[str],
) -> list[dict[str, Any]]:
    ordered = ["all_calls", *[stage for stage in stages if stage not in {"lost"}], "lost"]
    rank = {stage: index for index, stage in enumerate(ordered)}
    effective = sum(1 for call, _, _ in rows if call.duration_ms >= 15000)
    counts: dict[str, int] = {"all_calls": len(rows), "effective": effective}
    for stage in ordered:
        if stage in counts:
            continue
        if stage == "lost":
            counts[stage] = sum(1 for _, _, sales in rows if sales and sales.outcome == "lost")
            continue
        counts[stage] = sum(
            1
            for _, insight, sales in rows
            if sales
            and _is_opportunity(insight, sales)
            and (
                sales.outcome == "won"
                or (sales.outcome == "lost" and stage == "qualified")
                or (
                    sales.outcome != "lost"
                    and rank.get(sales.funnel_stage, -1) >= rank.get(stage, 10**6)
                )
            )
        )
    funnel: list[dict[str, Any]] = []
    previous = len(rows)
    for stage in ordered:
        count = counts.get(stage, 0)
        denominator = counts.get("qualified", previous) if stage == "lost" else previous
        funnel.append(
            {
                "key": stage,
                "count": count,
                "pass_rate": round(count * 100 / denominator, 1) if denominator else None,
                "drop_rate": (
                    None
                    if stage == "lost"
                    else round(max(previous - count, 0) * 100 / previous, 1)
                    if previous
                    else None
                ),
            }
        )
        if stage != "lost":
            previous = count
    return funnel


@router.get("/kpi/dashboard")
async def dashboard(
    principal: UserDep,
    session: TenantSession,
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: datetime | None = None,
    direction: str | None = None,
    team_id: UUID | None = None,
    operator_id: UUID | None = None,
    campaign_id: str | None = None,
    source: str | None = None,
    intent: str | None = None,
    certainty: str | None = None,
    operator_offset: Annotated[int, Query(ge=0)] = 0,
    campaign_offset: Annotated[int, Query(ge=0)] = 0,
    table_limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> dict[str, Any]:
    tenant_id = principal.tenant_id
    assert tenant_id is not None
    to_date = to or datetime.now(UTC)
    from_date = from_ or to_date - timedelta(days=30)
    if principal.role == "operator":
        operator_id = principal.id
        team_id = None
    conditions = [
        Call.tenant_id == tenant_id,
        Call.started_at >= from_date,
        Call.started_at <= to_date,
    ]
    for column, value in (
        (Call.direction, direction),
        (Call.campaign_id, campaign_id),
        (Call.source, source),
        (CallInsight.intent, intent),
        (SalesInsight.certainty, certainty),
    ):
        if value:
            conditions.append(column == value)
    if operator_id:
        conditions.append(
            select(CallOperatorAssignment.id)
            .where(
                CallOperatorAssignment.call_id == Call.id,
                CallOperatorAssignment.operator_id == operator_id,
                CallOperatorAssignment.superseded_at.is_(None),
            )
            .exists()
        )
    if team_id:
        conditions.append(
            select(CallOperatorAssignment.id)
            .join(TeamMembership, TeamMembership.operator_id == CallOperatorAssignment.operator_id)
            .where(
                CallOperatorAssignment.call_id == Call.id,
                TeamMembership.team_id == team_id,
                TeamMembership.valid_from <= Call.started_at,
                or_(TeamMembership.valid_to.is_(None), TeamMembership.valid_to > Call.started_at),
            )
            .exists()
        )
    stmt = (
        select(Call, CallInsight, SalesInsight)
        .outerjoin(CallInsight, CallInsight.call_id == Call.id)
        .outerjoin(SalesInsight, SalesInsight.call_id == Call.id)
        .where(and_(*conditions))
    )
    stmt = operator_scope.apply_operator_scope(stmt, principal)
    rows = (await session.execute(stmt.order_by(Call.started_at.desc()))).all()
    period = to_date - from_date
    previous_to = from_date
    previous_from = previous_to - period
    previous_conditions = [
        Call.tenant_id == tenant_id,
        Call.started_at >= previous_from,
        Call.started_at < previous_to,
        *conditions[3:],
    ]
    previous_stmt = (
        select(Call, CallInsight, SalesInsight)
        .outerjoin(CallInsight, CallInsight.call_id == Call.id)
        .outerjoin(SalesInsight, SalesInsight.call_id == Call.id)
        .where(and_(*previous_conditions))
    )
    previous_stmt = operator_scope.apply_operator_scope(previous_stmt, principal)
    previous_rows = (await session.execute(previous_stmt)).all()
    call_ids = [call.id for call, _, _ in rows]
    previous_call_ids = [call.id for call, _, _ in previous_rows]
    assignments = (
        (
            await session.execute(
                select(CallOperatorAssignment, User)
                .join(User, User.id == CallOperatorAssignment.operator_id)
                .where(
                    CallOperatorAssignment.call_id.in_(call_ids),
                    CallOperatorAssignment.superseded_at.is_(None),
                )
            )
        ).all()
        if call_ids
        else []
    )
    assignment_by_call = {item.call_id: user for item, user in assignments}
    scores = (
        (
            await session.execute(
                select(OperatorCallScore)
                .where(
                    OperatorCallScore.call_id.in_(call_ids), OperatorCallScore.status == "succeeded"
                )
                .order_by(OperatorCallScore.created_at.desc())
            )
        )
        .scalars()
        .all()
        if call_ids
        else []
    )
    latest_score: dict[UUID, OperatorCallScore] = {}
    for score in scores:
        latest_score.setdefault(score.call_id, score)
    tasks = (
        (await session.execute(select(FollowUpTask).where(FollowUpTask.call_id.in_(call_ids))))
        .scalars()
        .all()
        if call_ids
        else []
    )
    previous_tasks = (
        (
            await session.execute(
                select(FollowUpTask).where(FollowUpTask.call_id.in_(previous_call_ids))
            )
        )
        .scalars()
        .all()
        if previous_call_ids
        else []
    )
    task_by_call: dict[UUID, list[FollowUpTask]] = defaultdict(list)
    for task in tasks:
        task_by_call[task.call_id].append(task)
    utterance_rows = (
        (
            await session.execute(
                select(
                    Utterance.call_id,
                    Utterance.channel,
                    func.sum(Utterance.t_end_ms - Utterance.t_start_ms),
                )
                .where(Utterance.call_id.in_(call_ids))
                .group_by(Utterance.call_id, Utterance.channel)
            )
        ).all()
        if call_ids
        else []
    )
    talk: dict[UUID, dict[int, int]] = defaultdict(dict)
    for call_id, channel, duration in utterance_rows:
        talk[call_id][channel] = int(duration or 0)
    crm_conditions = [
        CrmOutcome.tenant_id == tenant_id,
        CrmOutcome.occurred_at >= from_date,
        CrmOutcome.occurred_at <= to_date,
    ]
    call_scoped_crm = principal.role == "operator" or any(
        value is not None for value in (operator_id, team_id, direction, intent, certainty)
    )
    if call_scoped_crm:
        crm_conditions.append(CrmOutcome.call_id.in_(call_ids))
    crm_rows = (
        (await session.execute(select(CrmOutcome).where(and_(*crm_conditions)))).scalars().all()
    )
    if campaign_id:
        crm_rows = [item for item in crm_rows if item.campaign_id == campaign_id]
    if source:
        crm_rows = [item for item in crm_rows if item.source == source]
    previous_crm_conditions = [
        CrmOutcome.tenant_id == tenant_id,
        CrmOutcome.occurred_at >= previous_from,
        CrmOutcome.occurred_at < previous_to,
    ]
    if call_scoped_crm:
        previous_crm_conditions.append(CrmOutcome.call_id.in_(previous_call_ids))
    previous_crm_rows = (
        (await session.execute(select(CrmOutcome).where(and_(*previous_crm_conditions))))
        .scalars()
        .all()
    )
    if campaign_id:
        previous_crm_rows = [item for item in previous_crm_rows if item.campaign_id == campaign_id]
    if source:
        previous_crm_rows = [item for item in previous_crm_rows if item.source == source]
    _, settings = await _settings(session, tenant_id)
    now = datetime.now(UTC)
    outcomes = Counter(item.outcome for _, _, item in rows if item)
    opportunity_rows = [
        (call, insight, item) for call, insight, item in rows if _is_opportunity(insight, item)
    ]
    opportunities = len(opportunity_rows)
    probable_threshold = float(settings["probable_confidence_threshold"])
    explicit_won = sum(
        1
        for _, _, item in opportunity_rows
        if item and item.outcome == "won" and item.certainty == "explicit"
    )
    known_ai = sum(
        1 for _, _, item in opportunity_rows if _has_known_ai_outcome(item, probable_threshold)
    )
    probable = sum(
        1
        for _, _, item in opportunity_rows
        if item and item.certainty == "probable" and item.confidence >= probable_threshold
    )
    previous_opportunity_rows = [
        (call, insight, item)
        for call, insight, item in previous_rows
        if _is_opportunity(insight, item)
    ]
    previous_opportunities = len(previous_opportunity_rows)
    previous_known_ai = sum(
        1
        for _, _, item in previous_opportunity_rows
        if _has_known_ai_outcome(item, probable_threshold)
    )
    previous_explicit_won = sum(
        1
        for _, _, item in previous_opportunity_rows
        if item and item.outcome == "won" and item.certainty == "explicit"
    )
    effective = sum(1 for call, _, _ in rows if call.duration_ms >= 15000)
    sla_hours = int(settings["follow_up_sla_hours"])
    due_tasks = [item for item in tasks if item.created_at + timedelta(hours=sla_hours) <= now]
    on_time = [
        item
        for item in due_tasks
        if item.status == "done"
        and item.completed_at
        and item.completed_at <= item.created_at + timedelta(hours=sla_hours)
    ]
    previous_due_tasks = [
        item
        for item in previous_tasks
        if item.created_at + timedelta(hours=sla_hours) <= previous_to
    ]
    previous_on_time = [
        item
        for item in previous_due_tasks
        if item.status == "done"
        and item.completed_at
        and item.completed_at <= previous_to
        and item.completed_at <= item.created_at + timedelta(hours=sla_hours)
    ]
    improved = sum(
        1
        for _, insight, _ in rows
        if insight
        and ((insight.sentiment_profile or {}).get("text") or {})
        .get("caller", {})
        .get("trajectory")
        == "improved"
    )
    sentiment_known = sum(
        1
        for _, insight, _ in rows
        if insight and ((insight.sentiment_profile or {}).get("text") or {}).get("caller")
    )
    previous_improved = sum(
        1
        for _, insight, _ in previous_rows
        if insight
        and ((insight.sentiment_profile or {}).get("text") or {})
        .get("caller", {})
        .get("trajectory")
        == "improved"
    )
    previous_sentiment_known = sum(
        1
        for _, insight, _ in previous_rows
        if insight and ((insight.sentiment_profile or {}).get("text") or {}).get("caller")
    )
    scored = [item.total_score for item in latest_score.values() if item.total_score is not None]
    crm_eligible = [
        item
        for item in crm_rows
        if item.outcome != "not_qualified"
        and (item.funnel_stage not in {None, "unknown"} or item.outcome in {"won", "lost"})
    ]
    crm_won = [item for item in crm_eligible if item.outcome == "won"]
    previous_crm_eligible = [
        item
        for item in previous_crm_rows
        if item.outcome != "not_qualified"
        and (item.funnel_stage not in {None, "unknown"} or item.outcome in {"won", "lost"})
    ]
    previous_crm_won = [item for item in previous_crm_eligible if item.outcome == "won"]
    revenue = sum(item.amount or 0 for item in crm_won)
    pipeline_value = sum(
        item.amount or 0 for item in crm_rows if item.outcome in {"interested", "follow_up"}
    )
    funnel = _funnel_rows(rows, list(settings["funnel_stages"]))
    previous_funnel = {
        item["key"]: item for item in _funnel_rows(previous_rows, list(settings["funnel_stages"]))
    }
    for item in funnel:
        previous_item = previous_funnel.get(item["key"])
        previous_count = previous_item["count"] if previous_item else 0
        item["previous_count"] = previous_count
        item["change_percent"] = (
            round((item["count"] - previous_count) * 100 / previous_count, 1)
            if previous_count
            else None
        )
    hot = []
    for call, insight, sales in rows:
        if (
            sales
            and sales.confidence >= settings["hot_opportunity_threshold"]
            and sales.outcome in {"interested", "follow_up"}
            and not task_by_call[call.id]
        ):
            hot.append(
                {
                    "type": "hot_opportunity",
                    "severity": "high",
                    "call_id": str(call.id),
                    "title": sales.product or (insight.summary if insight else "فرصت فروش"),
                    "due_at": sales.next_action_due_at,
                }
            )
    overdue = [
        {
            "type": "overdue_follow_up",
            "severity": "high",
            "call_id": str(item.call_id),
            "title": item.title,
            "due_at": item.due_date,
        }
        for item in tasks
        if item.status == "open" and item.due_date and item.due_date < now.date()
    ]
    review = [
        {
            "type": "needs_review",
            "severity": "normal",
            "call_id": str(call.id),
            "title": "اطمینان پایین تحلیل فروش",
            "due_at": None,
        }
        for call, _, sales in rows
        if sales
        and (
            sales.certainty == "unknown"
            or (sales.certainty == "probable" and sales.confidence < probable_threshold)
        )
    ]
    operator_stats: dict[str, dict[str, Any]] = {}
    for call, insight, sales in rows:
        user = assignment_by_call.get(call.id)
        if not user:
            continue
        key = str(user.id)
        stat = operator_stats.setdefault(
            key,
            {
                "operator_id": key,
                "operator_label": user.display_name or user.email,
                "calls": 0,
                "wins": 0,
                "opportunities": 0,
                "scores": [],
                "talk_agent_ms": 0,
                "talk_caller_ms": 0,
            },
        )
        stat["calls"] += 1
        stat["wins"] += int(
            bool(sales and sales.outcome == "won" and sales.certainty == "explicit")
        )
        stat["opportunities"] += int(_is_opportunity(insight, sales))
        if call.id in latest_score and latest_score[call.id].total_score is not None:
            stat["scores"].append(latest_score[call.id].total_score)
        stat["talk_caller_ms"] += talk[call.id].get(0, 0)
        stat["talk_agent_ms"] += talk[call.id].get(1, 0)
    operators = []
    for stat in operator_stats.values():
        agent_talk = stat.pop("talk_agent_ms")
        caller_talk = stat.pop("talk_caller_ms")
        total_talk = agent_talk + caller_talk
        values = stat.pop("scores")
        stat["conversion"] = _rate(stat["wins"], stat["opportunities"])
        stat["quality_score"] = round(sum(values) / len(values), 1) if values else None
        stat["sample_sufficient"] = stat["calls"] >= settings["minimum_sample_size"]
        stat["agent_talk_ratio"] = round(agent_talk * 100 / total_talk, 1) if total_talk else None
        operators.append(stat)
    campaign_counter: dict[str, dict[str, Any]] = {}
    for call, insight, sales in rows:
        key = call.campaign_id or call.source or "unknown"
        item = campaign_counter.setdefault(
            key, {"key": key, "calls": 0, "opportunities": 0, "wins": 0}
        )
        item["calls"] += 1
        item["opportunities"] += int(_is_opportunity(insight, sales))
        item["wins"] += int(
            bool(sales and sales.outcome == "won" and sales.certainty == "explicit")
        )
    for item in campaign_counter.values():
        item["conversion"] = _rate(item["wins"], item["opportunities"])
    goal_team_id = team_id
    if principal.role == "operator":
        goal_team_id = (
            await session.execute(
                select(TeamMembership.team_id)
                .where(
                    TeamMembership.tenant_id == tenant_id,
                    TeamMembership.operator_id == principal.id,
                    TeamMembership.valid_from <= to_date,
                    or_(TeamMembership.valid_to.is_(None), TeamMembership.valid_to > to_date),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
    goal_scope = (
        or_(KpiGoal.team_id.is_(None), KpiGoal.team_id == goal_team_id)
        if goal_team_id
        else KpiGoal.team_id.is_(None)
    )
    goals = (
        (
            await session.execute(
                select(KpiGoal).where(
                    KpiGoal.tenant_id == tenant_id,
                    KpiGoal.valid_from <= to_date,
                    KpiGoal.valid_to >= from_date,
                    goal_scope,
                )
            )
        )
        .scalars()
        .all()
    )
    goal_map = {
        item.metric: item.target_value
        for item in sorted(goals, key=lambda value: value.team_id is not None)
    }
    ai_rate = _rate_with_change(explicit_won, known_ai, previous_explicit_won, previous_known_ai)
    crm_rate = _rate_with_change(
        len(crm_won),
        len(crm_eligible),
        len(previous_crm_won),
        len(previous_crm_eligible),
    )
    coverage_rate = _rate_with_change(
        known_ai, opportunities, previous_known_ai, previous_opportunities
    )
    probable_rate = _rate_with_change(
        probable,
        opportunities,
        sum(
            1
            for _, _, item in previous_opportunity_rows
            if item and item.certainty == "probable" and item.confidence >= probable_threshold
        ),
        previous_opportunities,
    )
    follow_up_rate = _rate_with_change(
        len(on_time), len(due_tasks), len(previous_on_time), len(previous_due_tasks)
    )
    sentiment_rate = _rate_with_change(
        improved,
        sentiment_known,
        previous_improved,
        previous_sentiment_known,
    )
    quality = round(sum(scored) / len(scored), 1) if scored else None
    actuals = {
        "conversion_rate": ai_rate["value"],
        "quality_score": quality,
        "follow_up_sla_rate": follow_up_rate["value"],
    }
    achievements = [
        {
            "metric": metric,
            "actual": actuals.get(metric),
            "target": target,
            "achievement": round((actuals[metric] or 0) * 100 / target, 1) if target else None,
        }
        for metric, target in goal_map.items()
    ]
    topics = Counter(topic for _, insight, _ in rows if insight for topic in (insight.topics or []))
    objections = Counter(value for _, _, sales in rows if sales for value in sales.objections)
    previous_objections = Counter(
        value for _, _, sales in previous_rows if sales for value in sales.objections
    )
    products = Counter(sales.product for _, _, sales in rows if sales and sales.product)
    reasons = Counter(
        sales.win_loss_reason for _, _, sales in rows if sales and sales.win_loss_reason
    )
    if ai_rate["change"] is not None and ai_rate["change"] <= -10:
        review.append(
            {
                "type": "kpi_decline",
                "severity": "high",
                "call_id": None,
                "title": "افت معنادار نرخ برد تخمینی",
                "due_at": None,
            }
        )
    for objection, count in objections.items():
        previous_count = previous_objections[objection]
        if count >= 3 and count >= max(previous_count * 2, previous_count + 2):
            review.append(
                {
                    "type": "objection_surge",
                    "severity": "high",
                    "call_id": None,
                    "title": f"افزایش اعتراض: {objection}",
                    "due_at": None,
                }
            )
    criterion_values: dict[str, list[tuple[float, UUID, str | None]]] = defaultdict(list)
    for score in latest_score.values():
        for criterion in score.criteria_scores or []:
            title = str(criterion.get("title") or "").strip()
            value = criterion.get("score")
            if title and isinstance(value, (int, float)):
                criterion_values[title].append(
                    (float(value), score.call_id, criterion.get("evidence"))
                )
    coaching_rows = []
    for title, values in criterion_values.items():
        average = sum(item[0] for item in values) / len(values)
        evidence_item = max(values, key=lambda item: item[0])
        coaching_rows.append(
            {
                "title": title,
                "average": round(average, 1),
                "call_id": str(evidence_item[1]),
                "evidence": evidence_item[2],
            }
        )
    coaching_rows.sort(
        key=lambda item: item["average"] if isinstance(item["average"], float) else 0.0,
        reverse=True,
    )
    team_rows = (
        (
            await session.execute(
                select(Team)
                .where(Team.tenant_id == tenant_id, Team.active.is_(True))
                .order_by(Team.name)
            )
        )
        .scalars()
        .all()
    )
    operator_rows = (
        (
            await session.execute(
                select(User)
                .where(User.tenant_id == tenant_id, User.role == "operator")
                .order_by(User.display_name, User.email)
            )
        )
        .scalars()
        .all()
    )
    return {
        "from_date": from_date,
        "to_date": to_date,
        "role": principal.role,
        "settings": settings,
        "cards": {
            "total_calls": len(rows),
            "effective_calls": effective,
            "opportunities": opportunities,
            "explicit_wins": explicit_won,
            "probable_opportunities": probable,
            "probable_opportunity_rate": probable_rate,
            "unknown_outcomes": outcomes["unknown"],
            "ai_win_rate": ai_rate,
            "crm_conversion_rate": crm_rate,
            "outcome_coverage": coverage_rate,
            "revenue": revenue,
            "pipeline_value": pipeline_value,
            "currency": next((item.currency for item in crm_rows if item.currency), None),
            "quality_score": quality,
            "follow_up_sla_rate": follow_up_rate,
            "sentiment_improvement": sentiment_rate,
            "hot_unassigned": len(hot),
            "goal_achievement": achievements,
        },
        "funnel": funnel,
        "breakdowns": {
            "topics": topics.most_common(10),
            "objections": objections.most_common(10),
            "products": products.most_common(10),
            "win_loss_reasons": reasons.most_common(10),
            "campaigns": list(campaign_counter.values())[
                campaign_offset : campaign_offset + table_limit
            ],
            "campaigns_total": len(campaign_counter),
        },
        "operators": (
            operators[operator_offset : operator_offset + table_limit]
            if principal.role != "operator"
            else operators[:1]
        ),
        "operators_total": len(operators) if principal.role != "operator" else min(1, len(operators)),
        "actions": (hot + overdue + review)[:100],
        "coaching": {
            "strengths": coaching_rows[:3],
            "improvements": list(reversed(coaching_rows[-3:])),
        },
        "filters": {
            "directions": sorted({call.direction for call, _, _ in rows if call.direction}),
            "campaigns": sorted({call.campaign_id for call, _, _ in rows if call.campaign_id}),
            "sources": sorted({call.source for call, _, _ in rows if call.source}),
            "intents": sorted(
                {insight.intent for _, insight, _ in rows if insight and insight.intent}
            ),
            "certainties": sorted({sales.certainty for _, _, sales in rows if sales}),
            "teams": (
                [{"id": str(item.id), "name": item.name} for item in team_rows]
                if principal.role != "operator"
                else []
            ),
            "operators": [
                {"id": str(item.id), "name": item.display_name or item.email}
                for item in operator_rows
                if principal.role != "operator" or item.id == principal.id
            ],
        },
    }
