from __future__ import annotations

import json
from uuid import UUID

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import operational_tenant_ids, session_scope
from app.models import Call, CallInsight
from app.services.platform import AISERVICE_ROUTES, effective_models


def _vector_literal(values: list[float]) -> str:
    if not values or len(values) > 4096:
        raise ValueError("embedding dimension is invalid")
    return "[" + ",".join(format(float(value), ".9g") for value in values) + "]"


async def embed(content: str) -> tuple[list[float], str]:
    async with session_scope(None, staff=True) as control_session:
        settings = await effective_models(control_session)
    base_url = settings["voicesanj_base_url"].rstrip("/")
    api_key = settings["api_key"].strip()
    model = settings["embedding_model"].strip()
    if not base_url or not api_key or not model:
        raise RuntimeError("embedding provider is not configured")
    async with httpx.AsyncClient(timeout=120.0, follow_redirects=False) as client:
        response = await client.post(
            f"{base_url}{AISERVICE_ROUTES['embedding_route'][settings['embedding_route']]}",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": model, "input": content},
        )
    response.raise_for_status()
    body = response.json()
    vector = body.get("data", [{}])[0].get("embedding")
    if not isinstance(vector, list):
        raise RuntimeError("embedding provider returned no vector")
    return [float(value) for value in vector], model


def _cypher_value(value: object) -> str:
    return json.dumps(str(value), ensure_ascii=False).replace("$", "\\u0024")


async def _index_graph(
    session: AsyncSession, call: Call, insight: CallInsight, operator_id: UUID | None
) -> None:
    call_id = _cypher_value(call.id)
    tenant_id = _cypher_value(call.tenant_id)
    operator = _cypher_value(operator_id) if operator_id else None
    statements = [
        f"MERGE (c:Call {{id: {call_id}}}) SET c.tenant_id = {tenant_id}",
    ]
    if operator is not None:
        statements.append(
            f"MERGE (o:Operator {{id: {operator}}}) "
            f"MERGE (c:Call {{id: {call_id}}}) MERGE (o)-[:HANDLED]->(c)"
        )
    for topic in sorted(set((insight.topics or []) + (insight.keywords or [])))[:20]:
        value = _cypher_value(topic)
        statements.append(
            f"MERGE (t:Topic {{name: {value}}}) "
            f"MERGE (c:Call {{id: {call_id}}}) MERGE (c)-[:HAS_TOPIC]->(t)"
        )
    if insight.sentiment:
        value = _cypher_value(insight.sentiment)
        statements.append(
            f"MERGE (s:Sentiment {{name: {value}}}) "
            f"MERGE (c:Call {{id: {call_id}}}) MERGE (c)-[:EXPRESSED]->(s)"
        )
    for statement in statements:
        await session.execute(
            text(
                "SELECT * FROM ag_catalog.cypher('tenant_graph', $$"
                + statement
                + " RETURN 1"
                + "$$) AS (result ag_catalog.agtype)"
            )
        )


async def index_call(session: AsyncSession, tenant_id: UUID, call_id: UUID) -> None:
    call = await session.get(Call, call_id)
    insight = await session.get(CallInsight, call_id)
    if call is None or insight is None or call.tenant_id != tenant_id or not insight.summary:
        return
    operator_id = (
        await session.execute(
            text(
                "SELECT operator_id FROM call_operator_assignments "
                "WHERE tenant_id = :tenant_id AND call_id = :call_id "
                "AND superseded_at IS NULL ORDER BY assigned_at DESC LIMIT 1"
            ),
            {"tenant_id": tenant_id, "call_id": call_id},
        )
    ).scalar_one_or_none()
    await session.execute(
        text(
            "INSERT INTO call_knowledge(call_id, tenant_id, operator_id, summary) "
            "VALUES (:call_id, :tenant_id, :operator_id, :summary) "
            "ON CONFLICT (call_id) DO UPDATE SET operator_id = EXCLUDED.operator_id, "
            "summary = EXCLUDED.summary, vector_status = 'pending', graph_status = 'pending', "
            "error_detail = NULL, updated_at = now()"
        ),
        {
            "call_id": call_id,
            "tenant_id": tenant_id,
            "operator_id": operator_id,
            "summary": insight.summary,
        },
    )
    vector_status = "failed"
    graph_status = "failed"
    errors: list[str] = []
    try:
        vector, model = await embed(insight.summary)
        async with session.begin_nested():
            await session.execute(
                text(
                    "UPDATE call_knowledge SET embedding = CAST(:embedding AS vector), "
                    "embedding_model = :model, vector_status = 'ready', indexed_at = now() "
                    "WHERE call_id = :call_id AND tenant_id = :tenant_id"
                ),
                {
                    "embedding": _vector_literal(vector),
                    "model": model,
                    "call_id": call_id,
                    "tenant_id": tenant_id,
                },
            )
        vector_status = "ready"
    except Exception as exc:
        errors.append(f"vector: {exc}")
    try:
        async with session.begin_nested():
            await _index_graph(session, call, insight, operator_id)
        graph_status = "ready"
    except Exception as exc:
        errors.append(f"graph: {exc}")
    await session.execute(
        text(
            "UPDATE call_knowledge SET vector_status = :vector_status, "
            "graph_status = :graph_status, error_detail = :error, updated_at = now() "
            "WHERE call_id = :call_id AND tenant_id = :tenant_id"
        ),
        {
            "vector_status": vector_status,
            "graph_status": graph_status,
            "error": "; ".join(errors)[:4000] or None,
            "call_id": call_id,
            "tenant_id": tenant_id,
        },
    )


async def vector_call_ids(
    session: AsyncSession,
    tenant_id: UUID,
    question: str,
    limit: int,
    operator_id: UUID | None,
) -> list[UUID]:
    vector, model = await embed(question)
    operator_clause = "AND operator_id = :operator_id" if operator_id else ""
    rows = await session.execute(
        text(
            "SELECT call_id FROM call_knowledge WHERE tenant_id = :tenant_id "
            "AND vector_status = 'ready' AND embedding IS NOT NULL "
            "AND embedding_model = :model "
            f"{operator_clause} ORDER BY embedding <=> CAST(:embedding AS vector) LIMIT :limit"
        ),
        {
            "tenant_id": tenant_id,
            "operator_id": operator_id,
            "model": model,
            "embedding": _vector_literal(vector),
            "limit": limit,
        },
    )
    return [UUID(str(value)) for value in rows.scalars()]


async def backfill_next() -> str:
    async with session_scope(None, staff=True) as control_session:
        models = await effective_models(control_session)
    expected_model = models["embedding_model"].strip()
    for tenant_id in await operational_tenant_ids():
        async with session_scope(tenant_id) as session:
            call_id = (
                await session.execute(
                    text(
                        "SELECT i.call_id FROM call_insights i "
                        "JOIN calls c ON c.id = i.call_id "
                        "LEFT JOIN call_knowledge k ON k.call_id = i.call_id "
                        "WHERE i.tenant_id = :tenant_id AND i.summary IS NOT NULL "
                        "AND (k.call_id IS NULL OR k.vector_status <> 'ready' "
                        "OR k.graph_status <> 'ready' "
                        "OR k.embedding_model IS DISTINCT FROM :model) "
                        "ORDER BY c.created_at DESC LIMIT 1"
                    ),
                    {"tenant_id": tenant_id, "model": expected_model},
                )
            ).scalar_one_or_none()
            if call_id is not None:
                await index_call(session, tenant_id, UUID(str(call_id)))
                return f"indexed:{tenant_id}:{call_id}"
    return "idle"


async def graph_context(session: AsyncSession, call_ids: list[UUID]) -> str:
    if not call_ids:
        return ""
    values = ", ".join(_cypher_value(call_id) for call_id in call_ids)
    query = (
        "MATCH (c:Call)-[r]->(n) WHERE c.id IN ["
        + values
        + "] RETURN c.id, type(r), properties(n) LIMIT 100"
    )
    async with session.begin_nested():
        rows = (
            await session.execute(
                text(
                    "SELECT * FROM ag_catalog.cypher('tenant_graph', $$"
                    + query
                    + "$$) AS (call_id ag_catalog.agtype, relation ag_catalog.agtype, "
                    "properties ag_catalog.agtype)"
                )
            )
        ).all()
    return "\n".join(
        f"تماس {call_id}: رابطه {relation} با {properties}"
        for call_id, relation, properties in rows
    )
