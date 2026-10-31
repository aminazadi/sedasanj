"""Vector index for organization data that is not a call summary or a transcript.

Every source is described by one SQL query that yields the same columns (``source_id``,
``call_id``, ``access``, ``title``, ``content``, ``updated_at``). A source row is re-embedded
whenever its ``updated_at`` changes or its vectors were made with another embedding model, and
chunks of sources that no longer exist are removed. ``access`` decides who may retrieve a chunk:
``tenant`` for everyone in the organization, ``call`` for operators who were a party on
``call_id`` plus all non-operators, and ``admin`` for organization administrators only.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import Select, and_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import operational_tenant_ids, session_scope
from app.models import Call, OrgKnowledgeChunk
from app.services import operator_scope
from app.services.knowledge import (
    _chunks,
    _embedding_provider,
    _vector_literal,
    embed,
    expected_embedding,
)
from app.services.platform import effective_models

logger = logging.getLogger(__name__)

MAX_CHUNKS_PER_SOURCE_ROW = 200
RETRY_SECONDS = 60


@dataclass(frozen=True)
class Source:
    source_type: str
    title: str
    query: str


SOURCES: tuple[Source, ...] = (
    Source(
        "organization_memory",
        "حافظهٔ سازمان",
        "SELECT m.id AS source_id, NULL::uuid AS call_id, 'tenant' AS access, m.title AS title, "
        "m.category || ': ' || m.title || E'\\n' || m.content AS content, m.updated_at "
        "FROM organization_memories m WHERE m.tenant_id = :tenant_id AND m.status = 'active' "
        "AND 'assistant' = ANY(m.applies_to)",
    ),
    Source(
        "sales_insight",
        "تحلیل فروش",
        "SELECT s.call_id AS source_id, s.call_id, 'call' AS access, "
        "coalesce(s.product, s.funnel_stage) AS title, "
        "'funnel_stage: ' || s.funnel_stage || '; outcome: ' || s.outcome "
        "|| coalesce('; product: ' || s.product, '') "
        "|| coalesce('; objections: ' || array_to_string(s.objections, ', '), '') "
        "|| coalesce('; win_loss_reason: ' || s.win_loss_reason, '') "
        "|| coalesce('; next_action: ' || s.next_action, '') AS content, s.updated_at "
        "FROM sales_insights s WHERE s.tenant_id = :tenant_id "
        "AND NOT EXISTS (SELECT 1 FROM calls ic WHERE ic.id = s.call_id "
        "AND ic.direction = 'internal')",
    ),
    Source(
        "crm_outcome",
        "نتیجهٔ CRM",
        "SELECT o.id AS source_id, o.call_id, "
        "CASE WHEN o.call_id IS NULL THEN 'tenant' ELSE 'call' END AS access, "
        "coalesce(o.product, o.outcome) AS title, "
        "'outcome: ' || o.outcome || coalesce('; funnel_stage: ' || o.funnel_stage, '') "
        "|| coalesce('; product: ' || o.product, '') "
        "|| coalesce('; campaign: ' || o.campaign_id, '') "
        "|| coalesce('; source: ' || o.source, '') "
        "|| coalesce('; channel: ' || o.channel, '') AS content, o.updated_at "
        "FROM crm_outcomes o WHERE o.tenant_id = :tenant_id "
        "AND NOT EXISTS (SELECT 1 FROM calls ic WHERE ic.id = o.call_id "
        "AND ic.direction = 'internal')",
    ),
    Source(
        "follow_up_task",
        "وظیفهٔ پیگیری",
        "SELECT f.id AS source_id, f.call_id, 'call' AS access, f.title AS title, "
        "f.title || coalesce(E'\\n' || f.description, '') || '; status: ' || f.status "
        "|| coalesce('; priority: ' || f.priority, '') "
        "|| coalesce('; due: ' || f.due_date::text, '') AS content, f.updated_at "
        "FROM follow_up_tasks f WHERE f.tenant_id = :tenant_id "
        "AND NOT EXISTS (SELECT 1 FROM calls ic WHERE ic.id = f.call_id "
        "AND ic.direction = 'internal')",
    ),
    Source(
        "kpi_goal",
        "هدف KPI",
        "SELECT g.id AS source_id, NULL::uuid AS call_id, 'tenant' AS access, g.metric AS title, "
        "'metric: ' || g.metric || '; target: ' || g.target_value::text "
        "|| '; valid_from: ' || g.valid_from::text || '; valid_to: ' || g.valid_to::text "
        "|| coalesce('; team: ' || t.name, '') AS content, g.created_at AS updated_at "
        "FROM kpi_goals g LEFT JOIN teams t ON t.id = g.team_id WHERE g.tenant_id = :tenant_id",
    ),
    Source(
        "team",
        "تیم",
        "SELECT t.id AS source_id, NULL::uuid AS call_id, 'tenant' AS access, t.name AS title, "
        "'team: ' || t.name || '; active: ' || t.active::text AS content, "
        "t.created_at AS updated_at FROM teams t WHERE t.tenant_id = :tenant_id",
    ),
    Source(
        "contact",
        "مخاطب",
        "SELECT c.id AS source_id, NULL::uuid AS call_id, 'admin' AS access, c.name AS title, "
        "c.name || coalesce('; company: ' || c.company, '') "
        "|| coalesce('; email: ' || c.email, '') "
        "|| coalesce(E'\\n' || c.notes, '') AS content, c.updated_at "
        "FROM contacts c WHERE c.tenant_id = :tenant_id",
    ),
    Source(
        "scheduled_report",
        "گزارش زمان‌بندی‌شده",
        "SELECT r.id AS source_id, NULL::uuid AS call_id, 'admin' AS access, r.name AS title, "
        "r.name || E'\\n' || r.content AS content, "
        "coalesce(r.completed_at, r.created_at) AS updated_at "
        "FROM scheduled_report_runs r WHERE r.tenant_id = :tenant_id "
        "AND r.status = 'succeeded' AND r.content IS NOT NULL",
    ),
    Source(
        "operator_coaching",
        "کوچینگ اپراتور",
        "SELECT k.id AS source_id, k.call_id, 'call' AS access, "
        "k.operator_label AS title, k.operator_label "
        "|| CASE WHEN EXISTS (SELECT 1 FROM calls ic WHERE ic.id = k.call_id "
        "AND ic.direction = 'internal') THEN ' (تماس داخلی بین همکاران)' ELSE '' END "
        "|| E'\\n' || k.narrative AS content, "
        "coalesce(k.completed_at, k.created_at) AS updated_at "
        "FROM operator_call_coachings k WHERE k.tenant_id = :tenant_id "
        "AND k.status = 'succeeded' AND k.narrative IS NOT NULL",
    ),
)
SOURCE_BY_TYPE = {source.source_type: source for source in SOURCES}

_STALE_SQL = (
    "WITH src AS ({query}) SELECT s.source_id, s.call_id, s.access, s.title, s.content, "
    "s.updated_at FROM src s WHERE (NOT EXISTS (SELECT 1 FROM org_knowledge_chunks k "
    "WHERE k.tenant_id = :tenant_id AND k.source_type = :source_type "
    "AND k.source_id = s.source_id) "
    "OR EXISTS (SELECT 1 FROM org_knowledge_chunks k "
    "WHERE k.tenant_id = :tenant_id AND k.source_type = :source_type "
    "AND k.source_id = s.source_id "
    "AND (k.source_updated_at IS DISTINCT FROM s.updated_at OR k.vector_status <> 'ready' "
    "OR k.embedding_model IS DISTINCT FROM :model "
    "OR k.embedding_provider IS DISTINCT FROM :provider "
    "OR k.call_id IS DISTINCT FROM s.call_id OR k.access <> s.access))) "
    "AND NOT EXISTS (SELECT 1 FROM org_knowledge_chunks k "
    "WHERE k.tenant_id = :tenant_id AND k.source_type = :source_type "
    "AND k.source_id = s.source_id AND k.next_retry_at > now()) "
    "ORDER BY s.updated_at DESC LIMIT 1"
)

_ORPHAN_SQL = (
    "WITH src AS ({query}) DELETE FROM org_knowledge_chunks k "
    "WHERE k.tenant_id = :tenant_id AND k.source_type = :source_type "
    "AND NOT EXISTS (SELECT 1 FROM src s WHERE s.source_id = k.source_id)"
)

_COMPLETE_SQL = (
    "SELECT bool_and(vector_status = 'ready' AND embedding IS NOT NULL) "
    "FROM org_knowledge_chunks WHERE tenant_id = :tenant_id "
    "AND source_type = :source_type AND source_id = :source_id"
)

_BACKOFF_SQL = (
    "UPDATE org_knowledge_chunks SET attempt_count = attempt_count + 1, "
    "last_attempt_at = now(), next_retry_at = now() + "
    "(LEAST(3600, :retry * power(2, LEAST(attempt_count, 7))) * interval '1 second'), "
    "error_detail = :error WHERE tenant_id = :tenant_id AND source_type = :source_type "
    "AND source_id = :source_id"
)

_INSERT_READY_SQL = (
    "INSERT INTO org_knowledge_chunks (tenant_id, source_type, source_id, ordinal, call_id, "
    "access, title, content, content_sha256, source_updated_at, embedding, embedding_model, "
    "embedding_provider, vector_status, last_attempt_at) VALUES (:tenant_id, :source_type, "
    ":source_id, :ordinal, :call_id, :access, :title, :content, :digest, :updated_at, "
    "CAST(:embedding AS vector), :model, :provider, 'ready', now())"
)

_INSERT_FAILED_SQL = (
    "INSERT INTO org_knowledge_chunks (tenant_id, source_type, source_id, ordinal, call_id, "
    "access, title, content, content_sha256, source_updated_at, vector_status, attempt_count, "
    "last_attempt_at, next_retry_at, error_detail) VALUES (:tenant_id, :source_type, "
    ":source_id, :ordinal, :call_id, :access, :title, :content, :digest, :updated_at, "
    "'failed', 1, now(), now() + make_interval(secs => :retry), :error)"
)


def _row_text(row: Any) -> str:
    return str(row.content or "").strip()


async def index_source_row(session: AsyncSession, tenant_id: UUID, source: Source, row: Any) -> str:
    """(Re)embed one source row; returns ``ready``, ``kept`` or ``failed``."""
    chunks = _chunks(_row_text(row))[:MAX_CHUNKS_PER_SOURCE_ROW]
    base = {
        "tenant_id": tenant_id,
        "source_type": source.source_type,
        "source_id": row.source_id,
    }
    if not chunks:
        await session.execute(
            text(
                "DELETE FROM org_knowledge_chunks WHERE tenant_id = :tenant_id "
                "AND source_type = :source_type AND source_id = :source_id"
            ),
            base,
        )
        return "ready"
    embedded: list[tuple[list[float], str] | None] = []
    last_error = ""
    for chunk in chunks:
        try:
            embedded.append(await embed(chunk))
        except Exception as exc:
            embedded.append(None)
            last_error = str(exc)[:500]
    failures = sum(1 for item in embedded if item is None)
    if failures:
        complete = (await session.execute(text(_COMPLETE_SQL), base)).scalar_one_or_none()
        if complete is True:
            # Keep the previous complete vectors searchable and retry later.
            await session.execute(
                text(_BACKOFF_SQL),
                {**base, "retry": RETRY_SECONDS, "error": f"{failures} failed: {last_error}"},
            )
            return "kept"
    await session.execute(
        text(
            "DELETE FROM org_knowledge_chunks WHERE tenant_id = :tenant_id "
            "AND source_type = :source_type AND source_id = :source_id"
        ),
        base,
    )
    status = "ready"
    for ordinal, (chunk, result) in enumerate(zip(chunks, embedded, strict=True)):
        params = {
            **base,
            "ordinal": ordinal,
            "call_id": row.call_id,
            "access": row.access,
            "title": str(row.title or "")[:200],
            "content": chunk,
            "digest": hashlib.sha256(chunk.encode()).hexdigest(),
            "updated_at": row.updated_at,
        }
        try:
            if result is None:
                raise RuntimeError(last_error or "embedding failed")
            vector, model = result
            async with session.begin_nested():
                await session.execute(
                    text(_INSERT_READY_SQL),
                    {
                        **params,
                        "embedding": _vector_literal(vector),
                        "model": model,
                        "provider": _embedding_provider(model),
                    },
                )
        except Exception as exc:
            status = "failed"
            last_error = str(exc)[:500]
            async with session.begin_nested():
                await session.execute(
                    text(_INSERT_FAILED_SQL),
                    {**params, "retry": RETRY_SECONDS, "error": last_error},
                )
    return status


async def backfill_org_next() -> str:
    """Index one stale source row of the first tenant that has one."""
    async with session_scope(None, staff=True) as control_session:
        models = await effective_models(control_session)
    model, provider = expected_embedding(models)
    for tenant_id in await operational_tenant_ids():
        async with session_scope(tenant_id) as session:
            for source in SOURCES:
                params = {
                    "tenant_id": tenant_id,
                    "source_type": source.source_type,
                    "model": model,
                    "provider": provider,
                }
                row = (
                    (await session.execute(text(_STALE_SQL.format(query=source.query)), params))
                    .mappings()
                    .first()
                )
                if row is None:
                    await session.execute(
                        text(_ORPHAN_SQL.format(query=source.query)),
                        {"tenant_id": tenant_id, "source_type": source.source_type},
                    )
                    continue
                result = await index_source_row(session, tenant_id, source, _Row(row))
                return f"org-{result}:{tenant_id}:{source.source_type}:{row['source_id']}"
    return "idle"


class _Row:
    """Attribute access over a SQL mapping row."""

    def __init__(self, mapping: Any) -> None:
        self._mapping = mapping

    def __getattr__(self, name: str) -> Any:
        return self._mapping[name]


def _access_levels(role: str, *, operator: bool) -> list[str]:
    if operator:
        return ["call"]
    if role == "org_admin":
        return ["tenant", "call", "admin"]
    return ["tenant", "call"]


def search_statement(
    principal: Any,
    *,
    query_vector: list[float],
    model: str,
    source_types: list[str] | None,
    limit: int,
) -> Select[Any]:
    """Nearest chunks the principal may read, ordered by cosine distance."""
    chunk = OrgKnowledgeChunk
    operator = operator_scope.is_operator(principal)
    statement = select(
        chunk.source_type, chunk.source_id, chunk.call_id, chunk.title, chunk.content
    ).where(
        chunk.tenant_id == principal.tenant_id,
        chunk.vector_status == "ready",
        chunk.embedding.is_not(None),
        chunk.embedding_model == model,
        chunk.embedding_provider == _embedding_provider(model),
        chunk.access.in_(_access_levels(principal.role, operator=operator)),
    )
    if source_types:
        statement = statement.where(chunk.source_type.in_(source_types))
    if operator:
        visible = operator_scope.apply_operator_scope(
            select(Call.id).where(Call.tenant_id == principal.tenant_id), principal
        )
        statement = statement.where(and_(chunk.call_id.is_not(None), chunk.call_id.in_(visible)))
    return (
        statement.order_by(text("org_knowledge_chunks.embedding <=> CAST(:query_vector AS vector)"))
        .params(query_vector=_vector_literal(query_vector))
        .limit(limit)
    )


async def search(
    session: AsyncSession,
    principal: Any,
    query: str,
    *,
    source_types: list[str] | None,
    limit: int,
) -> list[dict[str, Any]]:
    vector, model = await embed(query)
    rows = await session.execute(
        search_statement(
            principal, query_vector=vector, model=model, source_types=source_types, limit=limit
        )
    )
    return [
        {
            "source_type": str(row.source_type),
            "source_id": str(row.source_id),
            "call_id": str(row.call_id) if row.call_id else None,
            "title": str(row.title),
            "content": str(row.content),
        }
        for row in rows
    ]


async def coverage_for_tenant(
    session: AsyncSession, tenant_id: UUID, model: str, provider: str
) -> dict[str, dict[str, int]]:
    """Per source: rows that exist, rows fully indexed with the current model, rows missing."""
    result: dict[str, dict[str, int]] = {}
    for source in SOURCES:
        counts = (
            (
                await session.execute(
                    text(
                        f"WITH src AS ({source.query}) SELECT count(*) AS total, "
                        "count(*) FILTER (WHERE EXISTS (SELECT 1 FROM org_knowledge_chunks k "
                        "WHERE k.tenant_id = :tenant_id AND k.source_type = :source_type "
                        "AND k.source_id = s.source_id) AND NOT EXISTS ("
                        "SELECT 1 FROM org_knowledge_chunks k WHERE k.tenant_id = :tenant_id "
                        "AND k.source_type = :source_type AND k.source_id = s.source_id "
                        "AND (k.vector_status <> 'ready' "
                        "OR k.source_updated_at IS DISTINCT FROM s.updated_at "
                        "OR k.embedding_model IS DISTINCT FROM :model "
                        "OR k.embedding_provider IS DISTINCT FROM :provider))) AS ready "
                        "FROM src s"
                    ),
                    {
                        "tenant_id": tenant_id,
                        "source_type": source.source_type,
                        "model": model,
                        "provider": provider,
                    },
                )
            )
            .mappings()
            .one()
        )
        total = int(counts["total"])
        ready = int(counts["ready"])
        result[source.source_type] = {"total": total, "ready": ready, "pending": total - ready}
    return result


def merge_coverage(items: list[dict[str, dict[str, int]]]) -> dict[str, dict[str, int]]:
    """Sum per-tenant coverage dictionaries produced by `coverage_for_tenant`."""
    total: dict[str, dict[str, int]] = {}
    for item in items:
        for source_type, counts in item.items():
            target = total.setdefault(source_type, {"total": 0, "ready": 0, "pending": 0})
            for key, value in counts.items():
                target[key] = target.get(key, 0) + value
    return total
