from __future__ import annotations

import hashlib
import json
from uuid import UUID

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import operational_tenant_ids, session_scope
from app.models import Call, CallInsight, Transcript
from app.services.apache_age import execute_cypher
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
        await execute_cypher(session, f"{statement} RETURN 1", ("result",))


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
                    "embedding_model = :model, vector_status = 'ready', indexed_at = now(), "
                    "attempt_count = 0, last_attempt_at = now(), next_retry_at = NULL "
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
        await session.execute(
            text(
                "UPDATE call_knowledge SET attempt_count = attempt_count + 1, "
                "last_attempt_at = now(), next_retry_at = now() + "
                "(LEAST(3600, 30 * power(2, LEAST(attempt_count, 7))) * interval '1 second') "
                "WHERE call_id = :call_id AND tenant_id = :tenant_id"
            ),
            {"call_id": call_id, "tenant_id": tenant_id},
        )
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
    if vector_status == "ready":
        await _index_transcript_chunks(session, call, tenant_id)


def _without_graph_error(detail: str | None) -> str | None:
    if not detail:
        return None
    if detail.startswith("graph: "):
        return None
    return detail.partition("; graph: ")[0].strip() or None


async def retry_graph(session: AsyncSession, tenant_id: UUID, call_id: UUID) -> bool:
    call = await session.get(Call, call_id)
    insight = await session.get(CallInsight, call_id)
    if call is None or insight is None or call.tenant_id != tenant_id or not insight.summary:
        return False
    row = (
        await session.execute(
            text(
                "SELECT operator_id, error_detail FROM call_knowledge "
                "WHERE call_id = :call_id AND tenant_id = :tenant_id"
            ),
            {"call_id": call_id, "tenant_id": tenant_id},
        )
    ).one_or_none()
    if row is None:
        return False
    operator_id = row[0]
    error_detail = _without_graph_error(str(row[1]) if row[1] else None)
    try:
        async with session.begin_nested():
            await _index_graph(session, call, insight, operator_id)
        graph_status = "ready"
    except Exception as exc:
        graph_status = "failed"
        graph_error = f"graph: {exc}"
        error_detail = f"{error_detail}; {graph_error}" if error_detail else graph_error
    await session.execute(
        text(
            "UPDATE call_knowledge SET graph_status = :graph_status, "
            "error_detail = :error, updated_at = now() "
            "WHERE call_id = :call_id AND tenant_id = :tenant_id"
        ),
        {
            "graph_status": graph_status,
            "error": error_detail[:4000] if error_detail else None,
            "call_id": call_id,
            "tenant_id": tenant_id,
        },
    )
    return graph_status == "ready"


def _chunks(content: str, size: int = 1200, overlap: int = 200) -> list[str]:
    text_value = " ".join(content.split())
    if not text_value:
        return []
    values: list[str] = []
    cursor = 0
    while cursor < len(text_value):
        values.append(text_value[cursor : cursor + size])
        if cursor + size >= len(text_value):
            break
        cursor += size - overlap
    return values[:100]


async def _index_transcript_chunks(
    session: AsyncSession, call: Call, tenant_id: UUID
) -> None:
    transcript = await session.get(Transcript, call.id)
    if transcript is None:
        return
    content = transcript.corrected_text or transcript.full_text
    chunks = _chunks(content)
    if not chunks:
        return
    await session.execute(
        text("DELETE FROM transcript_chunks WHERE call_id = :call_id AND tenant_id = :tenant_id"),
        {"call_id": call.id, "tenant_id": tenant_id},
    )
    for ordinal, chunk in enumerate(chunks):
        digest = hashlib.sha256(chunk.encode()).hexdigest()
        try:
            vector, model = await embed(chunk)
            await session.execute(
                text(
                    "INSERT INTO transcript_chunks "
                    "(tenant_id, call_id, ordinal, content, content_sha256, embedding, "
                    "source_revision_id, embedding_model, vector_status, last_attempt_at) "
                    "VALUES (:tenant_id, :call_id, :ordinal, :content, :digest, "
                    "CAST(:embedding AS vector), :revision_id, :model, 'ready', now())"
                ),
                {
                    "tenant_id": tenant_id,
                    "call_id": call.id,
                    "ordinal": ordinal,
                    "content": chunk,
                    "digest": digest,
                    "embedding": _vector_literal(vector),
                    "revision_id": transcript.active_revision_id,
                    "model": model,
                },
            )
        except Exception as exc:
            await session.execute(
                text(
                    "INSERT INTO transcript_chunks "
                    "(tenant_id, call_id, ordinal, content, content_sha256, source_revision_id, "
                    "vector_status, attempt_count, last_attempt_at, next_retry_at, error_detail) "
                    "VALUES (:tenant_id, :call_id, :ordinal, :content, :digest, :revision_id, "
                    "'failed', 1, now(), now() + interval '30 seconds', :error)"
                ),
                {
                    "tenant_id": tenant_id,
                    "call_id": call.id,
                    "ordinal": ordinal,
                    "content": chunk,
                    "digest": digest,
                    "revision_id": transcript.active_revision_id,
                    "error": str(exc)[:1000],
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


async def vector_call_context(
    session: AsyncSession,
    tenant_id: UUID,
    question: str,
    limit: int,
    operator_id: UUID | None,
    call_id: UUID | None = None,
) -> list[dict[str, object]]:
    vector, model = await embed(question)
    operator_clause = "AND k.operator_id = :operator_id" if operator_id else ""
    call_clause = "AND k.call_id = :call_id" if call_id else ""
    rows = await session.execute(
        text(
            "SELECT k.call_id, c.started_at, k.summary "
            "FROM call_knowledge k "
            "JOIN calls c ON c.id = k.call_id AND c.tenant_id = k.tenant_id "
            "WHERE k.tenant_id = :tenant_id "
            "AND k.vector_status = 'ready' AND k.embedding IS NOT NULL "
            "AND k.embedding_model = :model "
            f"{operator_clause} {call_clause} "
            "ORDER BY k.embedding <=> CAST(:embedding AS vector) LIMIT :limit"
        ),
        {
            "tenant_id": tenant_id,
            "operator_id": operator_id,
            "call_id": call_id,
            "model": model,
            "embedding": _vector_literal(vector),
            "limit": limit,
        },
    )
    return [
        {
            "call_id": UUID(str(row.call_id)),
            "started_at": row.started_at,
            "summary": str(row.summary),
        }
        for row in rows
    ]


async def vector_transcript_context(
    session: AsyncSession,
    tenant_id: UUID,
    question: str,
    limit: int,
    operator_id: UUID | None,
    call_id: UUID | None = None,
) -> list[dict[str, object]]:
    vector, model = await embed(question)
    operator_join = ""
    operator_clause = ""
    if operator_id:
        operator_join = (
            "JOIN call_operator_assignments a ON a.call_id = c.id "
            "AND a.tenant_id = c.tenant_id AND a.superseded_at IS NULL "
        )
        operator_clause = "AND a.operator_id = :operator_id"
    call_clause = "AND t.call_id = :call_id" if call_id else ""
    rows = await session.execute(
        text(
            "SELECT t.call_id, c.started_at, t.ordinal, t.content, "
            "1 - (t.embedding <=> CAST(:embedding AS vector)) AS score "
            "FROM transcript_chunks t "
            "JOIN calls c ON c.id = t.call_id AND c.tenant_id = t.tenant_id "
            f"{operator_join}"
            "WHERE t.tenant_id = :tenant_id AND t.vector_status = 'ready' "
            "AND t.embedding IS NOT NULL AND t.embedding_model = :model "
            f"{operator_clause} {call_clause} "
            "ORDER BY t.embedding <=> CAST(:embedding AS vector) LIMIT :limit"
        ),
        {
            "tenant_id": tenant_id,
            "operator_id": operator_id,
            "call_id": call_id,
            "model": model,
            "embedding": _vector_literal(vector),
            "limit": limit,
        },
    )
    return [
        {
            "call_id": UUID(str(row.call_id)),
            "started_at": row.started_at,
            "ordinal": int(row.ordinal),
            "content": str(row.content),
            "score": float(row.score),
        }
        for row in rows
    ]


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
                        "OR k.embedding_model IS DISTINCT FROM :model "
                        "OR (EXISTS (SELECT 1 FROM transcripts tr WHERE tr.call_id = i.call_id) "
                        "AND NOT EXISTS (SELECT 1 FROM transcript_chunks t "
                        "WHERE t.call_id = i.call_id AND t.tenant_id = i.tenant_id "
                        "AND t.vector_status = 'ready' AND t.embedding_model = :model))) "
                        "AND (k.next_retry_at IS NULL OR k.next_retry_at <= now()) "
                        "ORDER BY c.created_at DESC LIMIT 1"
                    ),
                    {"tenant_id": tenant_id, "model": expected_model},
                )
            ).scalar_one_or_none()
            if call_id is not None:
                await index_call(session, tenant_id, UUID(str(call_id)))
                return f"indexed:{tenant_id}:{call_id}"
    return "idle"


async def backfill_graph_next() -> str:
    for tenant_id in await operational_tenant_ids():
        async with session_scope(tenant_id) as session:
            call_id = (
                await session.execute(
                    text(
                        "SELECT call_id FROM call_knowledge "
                        "WHERE tenant_id = :tenant_id AND graph_status = 'failed' "
                        "AND updated_at <= now() - interval '30 seconds' "
                        "ORDER BY updated_at LIMIT 1"
                    ),
                    {"tenant_id": tenant_id},
                )
            ).scalar_one_or_none()
            if call_id is not None:
                ready = await retry_graph(session, tenant_id, UUID(str(call_id)))
                status = "indexed" if ready else "failed"
                return f"graph-{status}:{tenant_id}:{call_id}"
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
        rows = await execute_cypher(
            session, query, ("call_id", "relation", "properties")
        )
    return "\n".join(
        f"تماس {call_id}: رابطه {relation} با {properties}"
        for call_id, relation, properties in rows
    )
