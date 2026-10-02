from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiError
from app.metrics import assistant_tool_calls_total, assistant_tool_seconds
from app.models import (
    Call,
    CallInsight,
    CallOperatorAssignment,
    CrmOutcome,
    OperatorCallScore,
    SalesInsight,
    Transcript,
    User,
)
from app.services import knowledge, operator_scope

MAX_RESULTS = 25


class ToolArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WindowArguments(ToolArguments):
    from_date: datetime | None = None
    to_date: datetime | None = None


class SearchCallsArguments(WindowArguments):
    phone: str | None = Field(default=None, max_length=40)
    operator_id: UUID | None = None
    extension: str | None = Field(default=None, max_length=30)
    status: str | None = Field(default=None, max_length=40)
    direction: str | None = Field(default=None, max_length=30)
    topic: str | None = Field(default=None, max_length=120)
    sentiment: str | None = Field(default=None, max_length=30)
    campaign_id: str | None = Field(default=None, max_length=120)
    limit: int = Field(default=10, ge=1, le=MAX_RESULTS)
    offset: int = Field(default=0, ge=0, le=10_000)


class CallIdsArguments(ToolArguments):
    call_ids: list[UUID] = Field(min_length=1, max_length=10)


class SearchTranscriptsArguments(WindowArguments):
    query: str = Field(min_length=2, max_length=500)
    call_id: UUID | None = None
    limit: int = Field(default=8, ge=1, le=MAX_RESULTS)


class AnalyticsArguments(WindowArguments):
    operator_id: UUID | None = None
    campaign_id: str | None = Field(default=None, max_length=120)
    status: str | None = Field(default=None, max_length=40)
    direction: str | None = Field(default=None, max_length=30)
    sentiment: str | None = Field(default=None, max_length=30)
    topic: str | None = Field(default=None, max_length=120)


class OperatorPerformanceArguments(WindowArguments):
    operator_id: UUID | None = None


ChartType = Literal[
    "bar",
    "horizontal_bar",
    "line",
    "area",
    "pie",
    "donut",
    "radar",
    "radial_bar",
    "scatter",
    "composed",
    "treemap",
    "funnel",
]


class VisualizeStatisticsArguments(AnalyticsArguments):
    view: Literal["call_status", "call_trend", "operator_performance"] = "call_status"
    chart_types: list[ChartType] = Field(default_factory=list, max_length=4)


@dataclass(frozen=True)
class ToolContext:
    session: AsyncSession
    principal: Any
    bound_call_id: UUID | None


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    title: str
    description: str
    arguments: type[ToolArguments]
    executor: Callable[[ToolContext, ToolArguments], Awaitable[dict[str, Any]]]
    timeout_seconds: float = 30.0

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.arguments.model_json_schema(),
            },
        }


def _window(args: WindowArguments) -> tuple[datetime, datetime]:
    end = args.to_date or datetime.now(UTC)
    start = args.from_date or end - timedelta(days=30)
    if start >= end:
        raise ApiError("invalid_request", "from_date must be earlier than to_date")
    return start, end


async def _validate_operator(ctx: ToolContext, operator_id: UUID | None) -> UUID | None:
    principal = ctx.principal
    if operator_scope.is_operator(principal):
        if operator_id is not None and operator_id != principal.id:
            raise ApiError("forbidden", "operator scope cannot be changed")
        return principal.id
    if operator_id is None:
        return None
    row = await ctx.session.get(User, operator_id)
    if row is None or row.tenant_id != principal.tenant_id or row.role != "operator":
        raise ApiError("not_found", "operator not found")
    return operator_id


def _base_calls(ctx: ToolContext) -> Any:
    stmt = select(Call).where(Call.tenant_id == ctx.principal.tenant_id)
    stmt = operator_scope.apply_operator_scope(stmt, ctx.principal)
    if ctx.bound_call_id is not None:
        stmt = stmt.where(Call.id == ctx.bound_call_id)
    return stmt


def _apply_window(stmt: Any, start: datetime, end: datetime) -> Any:
    return stmt.where(Call.started_at >= start, Call.started_at <= end)


async def _search_calls(ctx: ToolContext, raw: ToolArguments) -> dict[str, Any]:
    args = SearchCallsArguments.model_validate(raw)
    start, end = _window(args)
    operator_id = await _validate_operator(ctx, args.operator_id)
    stmt = _apply_window(
        _base_calls(ctx).outerjoin(CallInsight, CallInsight.call_id == Call.id), start, end
    )
    if operator_id is not None and not operator_scope.is_operator(ctx.principal):
        stmt = stmt.where(
            select(CallOperatorAssignment.id)
            .where(
                CallOperatorAssignment.call_id == Call.id,
                CallOperatorAssignment.operator_id == operator_id,
                CallOperatorAssignment.superseded_at.is_(None),
            )
            .exists()
        )
    if args.phone:
        pattern = f"%{args.phone.strip()}%"
        stmt = stmt.where(or_(Call.caller_number.ilike(pattern), Call.dialed_number.ilike(pattern)))
    for column, value in (
        (Call.agent_extension, args.extension),
        (Call.status, args.status),
        (Call.direction, args.direction),
        (Call.campaign_id, args.campaign_id),
        (CallInsight.sentiment, args.sentiment),
    ):
        if value:
            stmt = stmt.where(column == value)
    if args.topic:
        stmt = stmt.where(CallInsight.topics.any(args.topic))
    rows = (
        await ctx.session.execute(
            stmt.add_columns(CallInsight.summary)
            .order_by(Call.started_at.desc())
            .offset(args.offset)
            .limit(args.limit)
        )
    ).all()
    return {
        "version": 1,
        "count": len(rows),
        "items": [
            {
                "call_id": str(call.id),
                "started_at": call.started_at.isoformat(),
                "duration_seconds": round(call.duration_ms / 1000),
                "status": call.status,
                "direction": call.direction,
                "summary": summary,
            }
            for call, summary in rows
        ],
    }


async def _visible_calls(ctx: ToolContext, call_ids: list[UUID]) -> list[Call]:
    if ctx.bound_call_id is not None and any(value != ctx.bound_call_id for value in call_ids):
        raise ApiError("not_found", "call not found")
    stmt = _base_calls(ctx).where(Call.id.in_(call_ids))
    rows = (await ctx.session.execute(stmt)).scalars().all()
    if len({row.id for row in rows}) != len(set(call_ids)):
        raise ApiError("not_found", "call not found")
    return rows


async def _call_details(ctx: ToolContext, raw: ToolArguments) -> dict[str, Any]:
    args = CallIdsArguments.model_validate(raw)
    rows = await _visible_calls(ctx, args.call_ids)
    insight_rows = (
        await ctx.session.execute(
            select(CallInsight).where(CallInsight.call_id.in_([row.id for row in rows]))
        )
    ).scalars().all()
    insights = {row.call_id: row for row in insight_rows}
    return {
        "version": 1,
        "count": len(rows),
        "items": [
            {
                "call_id": str(call.id),
                "started_at": call.started_at.isoformat(),
                "ended_at": call.ended_at.isoformat(),
                "duration_seconds": round(call.duration_ms / 1000),
                "status": call.status,
                "direction": call.direction,
                "caller_number": call.caller_number,
                "dialed_number": call.dialed_number,
                "agent_extension": call.agent_extension,
                "summary": insights.get(call.id).summary if insights.get(call.id) else None,
            }
            for call in rows
        ],
    }


def _snippet(text: str, query: str, size: int = 500) -> str:
    normalized = text.strip()
    position = normalized.casefold().find(query.casefold())
    if position < 0:
        return normalized[:size]
    start = max(0, position - size // 3)
    return normalized[start : start + size]


async def _search_transcripts(ctx: ToolContext, raw: ToolArguments) -> dict[str, Any]:
    args = SearchTranscriptsArguments.model_validate(raw)
    start, end = _window(args)
    call_stmt = _apply_window(_base_calls(ctx), start, end).subquery()
    stmt = (
        select(Transcript.call_id, Transcript.full_text, Call.started_at)
        .join(Call, Call.id == Transcript.call_id)
        .join(call_stmt, call_stmt.c.id == Transcript.call_id)
        .where(func.to_tsvector("simple", Transcript.full_text).op("@@")(
            func.websearch_to_tsquery("simple", args.query)
        ))
    )
    if args.call_id is not None:
        if ctx.bound_call_id is not None and args.call_id != ctx.bound_call_id:
            raise ApiError("not_found", "call not found")
        stmt = stmt.where(Transcript.call_id == args.call_id)
    rows = (await ctx.session.execute(stmt.order_by(Call.started_at.desc()).limit(args.limit))).all()
    items = [
        {
            "call_id": str(call_id),
            "started_at": started_at.isoformat(),
            "snippet": _snippet(full_text, args.query),
            "match": "full_text",
        }
        for call_id, full_text, started_at in rows
    ]
    if len(items) < args.limit:
        try:
            semantic = await knowledge.vector_transcript_context(
                ctx.session,
                ctx.principal.tenant_id,
                args.query,
                args.limit,
                ctx.principal.id if operator_scope.is_operator(ctx.principal) else None,
                args.call_id or ctx.bound_call_id,
            )
        except Exception:
            semantic = []
        known = {item["call_id"] for item in items}
        for row in semantic:
            call_id = str(row["call_id"])
            if call_id in known:
                continue
            items.append({
                "call_id": call_id,
                "started_at": row["started_at"].isoformat(),
                "snippet": str(row["content"])[:500],
                "match": "semantic_transcript",
                "score": row.get("score"),
            })
            if len(items) >= args.limit:
                break
    return {"version": 1, "count": len(items), "items": items}


async def _call_analysis(ctx: ToolContext, raw: ToolArguments) -> dict[str, Any]:
    args = CallIdsArguments.model_validate(raw)
    calls = await _visible_calls(ctx, args.call_ids)
    ids = [row.id for row in calls]
    insights = {
        row.call_id: row
        for row in (await ctx.session.execute(select(CallInsight).where(CallInsight.call_id.in_(ids)))).scalars()
    }
    sales = {
        row.call_id: row
        for row in (await ctx.session.execute(select(SalesInsight).where(SalesInsight.call_id.in_(ids)))).scalars()
    }
    crm = {
        row.call_id: row
        for row in (await ctx.session.execute(select(CrmOutcome).where(CrmOutcome.call_id.in_(ids)))).scalars()
        if row.call_id is not None
    }
    items = []
    for call in calls:
        insight = insights.get(call.id)
        sale = sales.get(call.id)
        outcome = crm.get(call.id)
        items.append({
            "call_id": str(call.id),
            "started_at": call.started_at.isoformat(),
            "summary": insight.summary if insight else None,
            "intent": insight.intent if insight else None,
            "topics": insight.topics if insight else [],
            "keywords": insight.keywords if insight else [],
            "sentiment": insight.sentiment if insight else None,
            "sentiment_profile": insight.sentiment_profile if insight else None,
            "entities": insight.ner if insight else None,
            "action_items": insight.action_items if insight else None,
            "sales_inference": {
                "outcome": sale.outcome,
                "certainty": sale.certainty,
                "confidence": sale.confidence,
                "product": sale.product,
                "objections": sale.objections,
                "next_action": sale.next_action,
            } if sale else None,
            "crm_outcome": {
                "outcome": outcome.outcome,
                "amount": outcome.amount,
                "currency": outcome.currency,
                "product": outcome.product,
            } if outcome else None,
        })
    return {"version": 1, "count": len(items), "items": items}


async def _analytics(ctx: ToolContext, raw: ToolArguments) -> dict[str, Any]:
    args = AnalyticsArguments.model_validate(raw)
    start, end = _window(args)
    operator_id = await _validate_operator(ctx, args.operator_id)
    stmt = _apply_window(_base_calls(ctx), start, end)
    if operator_id is not None and not operator_scope.is_operator(ctx.principal):
        stmt = stmt.where(select(CallOperatorAssignment.id).where(
            CallOperatorAssignment.call_id == Call.id,
            CallOperatorAssignment.operator_id == operator_id,
            CallOperatorAssignment.superseded_at.is_(None),
        ).exists())
    for column, value in (
        (Call.campaign_id, args.campaign_id),
        (Call.status, args.status),
        (Call.direction, args.direction),
    ):
        if value:
            stmt = stmt.where(column == value)
    if args.sentiment or args.topic:
        stmt = stmt.join(CallInsight, CallInsight.call_id == Call.id)
        if args.sentiment:
            stmt = stmt.where(CallInsight.sentiment == args.sentiment)
        if args.topic:
            stmt = stmt.where(CallInsight.topics.any(args.topic))
    filtered = stmt.subquery()
    query = select(
        func.count(filtered.c.id),
        func.coalesce(func.sum(filtered.c.duration_ms), 0),
        func.coalesce(func.avg(filtered.c.duration_ms), 0),
    )
    total, duration, average = (await ctx.session.execute(query)).one()
    status_rows = (await ctx.session.execute(
        select(filtered.c.status, func.count()).group_by(filtered.c.status)
    )).all()
    return {
        "version": 1,
        "from_date": start.isoformat(),
        "to_date": end.isoformat(),
        "total_calls": int(total),
        "total_minutes": round(int(duration) / 60000, 1),
        "average_minutes": round(float(average) / 60000, 1),
        "statuses": {str(key): int(value) for key, value in status_rows},
    }


async def _operator_performance(ctx: ToolContext, raw: ToolArguments) -> dict[str, Any]:
    args = OperatorPerformanceArguments.model_validate(raw)
    start, end = _window(args)
    operator_id = await _validate_operator(ctx, args.operator_id)
    stmt = select(
        OperatorCallScore.operator_id,
        OperatorCallScore.operator_label,
        func.avg(OperatorCallScore.total_score),
        func.count(OperatorCallScore.id),
    ).where(
        OperatorCallScore.tenant_id == ctx.principal.tenant_id,
        OperatorCallScore.status == "succeeded",
        OperatorCallScore.created_at >= start,
        OperatorCallScore.created_at <= end,
    )
    if operator_id is not None:
        stmt = stmt.where(OperatorCallScore.operator_id == operator_id)
    rows = (await ctx.session.execute(
        stmt.group_by(OperatorCallScore.operator_id, OperatorCallScore.operator_label)
        .order_by(func.avg(OperatorCallScore.total_score).desc())
        .limit(MAX_RESULTS)
    )).all()
    return {
        "version": 1,
        "from_date": start.isoformat(),
        "to_date": end.isoformat(),
        "count": len(rows),
        "items": [
            {
                "operator_id": str(row[0]) if row[0] else None,
                "operator_label": row[1],
                "average_score": round(float(row[2]), 1),
                "scored_calls": int(row[3]),
            }
            for row in rows
        ],
    }


async def _visualize_statistics(ctx: ToolContext, raw: ToolArguments) -> dict[str, Any]:
    args = VisualizeStatisticsArguments.model_validate(raw)
    if args.view == "operator_performance":
        result = await _operator_performance(
            ctx,
            OperatorPerformanceArguments(
                from_date=args.from_date,
                to_date=args.to_date,
                operator_id=args.operator_id,
            ),
        )
        score_data = [
            {"label": item["operator_label"] or "اپراتور نامشخص", "value": item["average_score"]}
            for item in result["items"]
        ]
        volume_data = [
            {"label": item["operator_label"] or "اپراتور نامشخص", "value": item["scored_calls"]}
            for item in result["items"]
        ]
        chart_types = args.chart_types or ["bar", "radar"]
        result["charts"] = [
            _chart_payload(
                f"operator-performance-{index}",
                "عملکرد اپراتورها",
                chart_type,
                [
                    {**score, "secondary_value": volume["value"]}
                    for score, volume in zip(score_data, volume_data, strict=True)
                ],
                "میانگین امتیاز",
                "تعداد تماس",
                len(chart_types),
            )
            for index, chart_type in enumerate(chart_types)
        ]
        return result

    result = await _analytics(
        ctx,
        AnalyticsArguments(
            from_date=args.from_date,
            to_date=args.to_date,
            operator_id=args.operator_id,
            campaign_id=args.campaign_id,
            status=args.status,
            direction=args.direction,
            sentiment=args.sentiment,
            topic=args.topic,
        ),
    )
    if args.view == "call_trend":
        start, end = _window(args)
        operator_id = await _validate_operator(ctx, args.operator_id)
        trend_stmt = _apply_window(_base_calls(ctx), start, end)
        if operator_id is not None and not operator_scope.is_operator(ctx.principal):
            trend_stmt = trend_stmt.where(select(CallOperatorAssignment.id).where(
                CallOperatorAssignment.call_id == Call.id,
                CallOperatorAssignment.operator_id == operator_id,
                CallOperatorAssignment.superseded_at.is_(None),
            ).exists())
        for column, value in (
            (Call.campaign_id, args.campaign_id),
            (Call.status, args.status),
            (Call.direction, args.direction),
        ):
            if value:
                trend_stmt = trend_stmt.where(column == value)
        if args.sentiment or args.topic:
            trend_stmt = trend_stmt.join(CallInsight, CallInsight.call_id == Call.id)
            if args.sentiment:
                trend_stmt = trend_stmt.where(CallInsight.sentiment == args.sentiment)
            if args.topic:
                trend_stmt = trend_stmt.where(CallInsight.topics.any(args.topic))
        filtered = trend_stmt.subquery()
        day = func.date_trunc("day", filtered.c.started_at).label("day")
        rows = (await ctx.session.execute(
            select(day, func.count(), func.coalesce(func.avg(filtered.c.duration_ms), 0))
            .group_by(day)
            .order_by(day)
        )).all()
        data = [
            {
                "label": row[0].date().isoformat(),
                "value": int(row[1]),
                "secondary_value": round(float(row[2]) / 60000, 1),
            }
            for row in rows
        ]
        chart_types = args.chart_types or ["line", "area"]
        title = "روند تماس‌ها"
        secondary_label = "میانگین مدت (دقیقه)"
    else:
        data = [
            {"label": str(label), "value": value}
            for label, value in result["statuses"].items()
        ]
        chart_types = args.chart_types or ["donut"]
        title = "توزیع وضعیت تماس‌ها"
        secondary_label = None
    result["charts"] = [
        _chart_payload(
            f"{args.view}-{index}",
            title,
            chart_type,
            data,
            "تعداد تماس",
            secondary_label,
            len(chart_types),
        )
        for index, chart_type in enumerate(chart_types)
    ]
    return result


def _chart_payload(
    chart_id: str,
    title: str,
    chart_type: ChartType,
    data: list[dict[str, Any]],
    value_label: str,
    secondary_value_label: str | None,
    chart_count: int,
) -> dict[str, Any]:
    return {
        "id": chart_id,
        "title": title,
        "type": chart_type,
        "size": "half" if chart_count > 1 else "full",
        "value_label": value_label,
        "secondary_value_label": secondary_value_label,
        "data": data,
    }


TOOLS = (
    ToolDefinition("search_calls", "جست‌وجوی تماس‌ها", "Find calls using safe filters.", SearchCallsArguments, _search_calls),
    ToolDefinition("get_call_details", "دریافت جزئیات تماس", "Get metadata for specific visible calls.", CallIdsArguments, _call_details),
    ToolDefinition("search_transcripts", "جست‌وجوی متن مکالمات", "Search visible call transcripts and semantic summaries.", SearchTranscriptsArguments, _search_transcripts, 120),
    ToolDefinition("get_call_analysis", "دریافت تحلیل تماس‌ها", "Get analysis, sales inference, and authoritative CRM outcome.", CallIdsArguments, _call_analysis),
    ToolDefinition("get_call_analytics", "دریافت آمار تماس‌ها", "Calculate exact call statistics from the database.", AnalyticsArguments, _analytics),
    ToolDefinition("get_operator_performance", "دریافت عملکرد اپراتورها", "Get access-controlled operator scoring statistics.", OperatorPerformanceArguments, _operator_performance),
    ToolDefinition("visualize_statistics", "ترسیم نمودار آماری", "Create exact, access-controlled charts. Choose up to four suitable types from bar, horizontal_bar, line, area, pie, donut, radar, radial_bar, scatter, composed, treemap, and funnel. Use call_trend for time-based charts, call_status for distributions, and operator_performance for comparisons.", VisualizeStatisticsArguments, _visualize_statistics),
)
TOOL_BY_NAME = {tool.name: tool for tool in TOOLS}


def schemas(enabled: set[str] | None = None) -> list[dict[str, Any]]:
    return [tool.schema() for tool in TOOLS if enabled is None or tool.name in enabled]


def title(name: str) -> str:
    tool = TOOL_BY_NAME.get(name)
    return tool.title if tool else "ابزار ناشناخته"


def fingerprint(name: str, arguments: dict[str, Any]) -> str:
    payload = json.dumps([name, arguments], sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


async def execute(
    name: str, arguments: dict[str, Any], ctx: ToolContext
) -> tuple[dict[str, Any], int]:
    tool = TOOL_BY_NAME.get(name)
    if tool is None:
        raise ApiError("invalid_request", "unknown assistant tool")
    parsed = tool.arguments.model_validate(arguments)
    started = time.perf_counter()
    try:
        async with ctx.session.begin_nested():
            result = await asyncio.wait_for(tool.executor(ctx, parsed), timeout=tool.timeout_seconds)
    except Exception:
        assistant_tool_calls_total.labels(tool=name, status="failed").inc()
        raise
    elapsed = time.perf_counter() - started
    assistant_tool_calls_total.labels(tool=name, status="succeeded").inc()
    assistant_tool_seconds.labels(tool=name).observe(elapsed)
    return result, round(elapsed * 1000)


def preview(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": 1,
        "count": int(result.get("count", result.get("total_calls", 0)) or 0),
        "summary": result_summary(result),
        "charts": result.get("charts", []),
    }


def result_summary(result: dict[str, Any]) -> str:
    if "total_calls" in result:
        return f"{int(result['total_calls'])} تماس بررسی شد"
    return f"{int(result.get('count', 0))} نتیجه دریافت شد"
