from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services import knowledge


class _Result:
    def __init__(self, value: object = None) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object:
        return self._value


class _Session:
    def __init__(self, transcript: SimpleNamespace, fail_inserts: set[int] | None = None) -> None:
        self.transcript = transcript
        self.fail_inserts = fail_inserts or set()
        self.statements: list[tuple[str, dict[str, object]]] = []
        self.savepoints = 0
        self.open_savepoints = 0
        self.chunk_inserts = 0

    async def get(self, model: object, key: object) -> SimpleNamespace:
        return self.transcript

    @asynccontextmanager
    async def begin_nested(self):
        self.savepoints += 1
        self.open_savepoints += 1
        try:
            yield
        finally:
            self.open_savepoints -= 1

    async def execute(self, statement: object, params: dict[str, object] | None = None):
        sql = str(statement)
        self.statements.append((sql, params or {}))
        if sql.startswith("INSERT INTO transcript_chunks") and "'ready'" in sql:
            self.chunk_inserts += 1
            if self.chunk_inserts in self.fail_inserts:
                assert self.open_savepoints == 1, "chunk insert must run inside a savepoint"
                raise RuntimeError("different vector dimensions")
            assert self.open_savepoints == 1, "chunk insert must run inside a savepoint"
        return _Result()


def _call_and_transcript(text_value: str) -> tuple[SimpleNamespace, SimpleNamespace]:
    call_id = uuid4()
    call = SimpleNamespace(id=call_id)
    transcript = SimpleNamespace(
        corrected_text=text_value, full_text="raw", active_revision_id=uuid4()
    )
    return call, transcript


def test_chunks_cover_long_transcripts_beyond_the_old_hundred_chunk_cap() -> None:
    content = "کلمه " * 60000
    chunks = knowledge._chunks(content)
    assert len(chunks) > 100
    assert chunks[-1] in " ".join(content.split())
    assert " ".join(content.split()).endswith(chunks[-1])


def test_chunks_are_still_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(knowledge, "MAX_TRANSCRIPT_CHUNKS", 50)
    chunks = knowledge._chunks("ب" * 500_000)
    assert len(chunks) == 50


def test_chunk_cap_is_far_above_a_two_hour_call() -> None:
    assert knowledge.MAX_TRANSCRIPT_CHUNKS >= 10000


@pytest.mark.asyncio
async def test_failed_chunk_is_recorded_and_call_is_backed_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call, transcript = _call_and_transcript("الف " * 1000)
    session = _Session(transcript, fail_inserts={2})

    async def fake_embed(content: str) -> tuple[list[float], str]:
        return [0.1, 0.2, 0.3], "model-x"

    monkeypatch.setattr(knowledge, "embed", fake_embed)

    await knowledge._index_transcript_chunks(session, call, uuid4())  # type: ignore[arg-type]

    sqls = [sql for sql, _ in session.statements]
    failed_rows = [
        s for s in sqls if "'failed'" in s and s.startswith("INSERT INTO transcript_chunks")
    ]
    assert len(failed_rows) == 1
    backoff = [s for s in sqls if s.startswith("UPDATE call_knowledge SET attempt_count")]
    assert len(backoff) == 1
    assert "next_retry_at" in backoff[0]
    assert session.open_savepoints == 0


@pytest.mark.asyncio
async def test_all_chunks_ready_leaves_call_without_backoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call, transcript = _call_and_transcript("الف " * 1000)
    session = _Session(transcript)

    async def fake_embed(content: str) -> tuple[list[float], str]:
        return [0.1] * 768, "model-768"

    monkeypatch.setattr(knowledge, "embed", fake_embed)

    await knowledge._index_transcript_chunks(session, call, uuid4())  # type: ignore[arg-type]

    sqls = [sql for sql, _ in session.statements]
    assert not any(s.startswith("UPDATE call_knowledge") for s in sqls)
    assert session.chunk_inserts >= 1


@pytest.mark.asyncio
async def test_backfill_selects_partial_and_stale_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[str] = []
    tenant_id = uuid4()

    @asynccontextmanager
    async def fake_scope(tid: object = None, **kwargs: object):
        class _S:
            async def execute(self, statement: object, params: object = None) -> _Result:
                captured.append(str(statement))
                return _Result(None)

        yield _S()

    async def fake_models(session: object) -> dict[str, str]:
        return {
            "embedding_provider": "aiservice",
            "embedding_model": "m",
            "ninerouter_embedding_model": "",
        }

    async def fake_tenants() -> list[object]:
        return [tenant_id]

    monkeypatch.setattr(knowledge, "session_scope", fake_scope)
    monkeypatch.setattr(knowledge, "effective_models", fake_models)
    monkeypatch.setattr(knowledge, "operational_tenant_ids", fake_tenants)

    assert await knowledge.backfill_next() == "idle"

    sql = captured[0]
    assert "t.vector_status <> 'ready'" in sql
    assert "t.source_revision_id IS DISTINCT FROM tr.active_revision_id" in sql
    assert sql.count("(") == sql.count(")")


class _Mappings:
    def __init__(self, row: dict[str, int]) -> None:
        self._row = row

    def mappings(self) -> _Mappings:
        return self

    def one(self) -> dict[str, int]:
        return self._row

    def scalar_one(self) -> int:
        return 7


@pytest.mark.asyncio
async def test_coverage_reports_every_source_and_unindexed_tables() -> None:
    queries: list[str] = []

    class _S:
        async def execute(self, statement: object, params: dict[str, object] | None = None):
            sql = str(statement)
            queries.append(sql)
            if "FROM call_insights i" in sql:
                assert params is not None and params["model"] == "m"
                return _Mappings({"with_summary": 5, "ready": 3, "failed": 1, "pending": 1})
            if "WITH per_call" in sql:
                assert (
                    params is not None and params["max_chunks"] == knowledge.MAX_TRANSCRIPT_CHUNKS
                )
                return _Mappings({"total": 4, "complete": 2, "partial": 1, "stale": 1})
            return _Mappings({})

    result = await knowledge.coverage_for_tenant(_S(), uuid4(), "m", "aiservice")  # type: ignore[arg-type]

    assert result["calls_total"] == 7
    assert result["call_summary"] == {"with_summary": 5, "ready": 3, "failed": 1, "pending": 1}
    assert result["transcript"]["stale"] == 1  # type: ignore[index]
    unindexed = result["unindexed_sources"]
    assert set(unindexed) == {name for name, _ in knowledge.UNINDEXED_SOURCES}  # type: ignore[arg-type]
    assert "chat_messages" in unindexed  # type: ignore[operator]
    assert all("tenant_id = :tenant_id" in q for q in queries)


def test_merge_coverage_sums_tenants() -> None:
    one = {
        "calls_total": 2,
        "call_summary": {"ready": 1},
        "transcript": {"partial": 1},
        "unindexed_sources": {"contacts": 3},
    }
    two = {
        "calls_total": 5,
        "call_summary": {"ready": 4, "failed": 2},
        "transcript": {"partial": 0},
        "unindexed_sources": {"contacts": 1},
    }
    merged = knowledge.merge_coverage([one, two])
    assert merged == {
        "calls_total": 7,
        "call_summary": {"ready": 5, "failed": 2},
        "transcript": {"partial": 1},
        "unindexed_sources": {"contacts": 4},
    }


def test_expected_embedding_follows_provider() -> None:
    direct = {
        "embedding_provider": "ninerouter_direct",
        "ninerouter_embedding_model": " bge ",
        "embedding_model": "x",
    }
    native = {
        "embedding_provider": "aiservice",
        "ninerouter_embedding_model": "",
        "embedding_model": " e5 ",
    }
    assert knowledge.expected_embedding(direct) == ("ninerouter_direct:bge", "ninerouter_direct")
    assert knowledge.expected_embedding(native) == ("e5", "aiservice")


@pytest.mark.asyncio
async def test_failed_embedding_keeps_previous_complete_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call, transcript = _call_and_transcript("الف " * 1000)

    class _CompleteSession(_Session):
        async def execute(self, statement: object, params: dict[str, object] | None = None):
            sql = str(statement)
            self.statements.append((sql, params or {}))
            if "bool_and" in sql:
                return _Result(True)
            return _Result()

    session = _CompleteSession(transcript)

    async def broken_embed(content: str) -> tuple[list[float], str]:
        raise RuntimeError("provider down")

    monkeypatch.setattr(knowledge, "embed", broken_embed)

    await knowledge._index_transcript_chunks(session, call, uuid4())  # type: ignore[arg-type]

    sqls = [sql for sql, _ in session.statements]
    assert not any(s.startswith("DELETE FROM transcript_chunks") for s in sqls)
    assert any(s.startswith("UPDATE call_knowledge SET attempt_count") for s in sqls)


@pytest.mark.asyncio
async def test_call_without_summary_still_gets_transcript_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid4()
    call = SimpleNamespace(id=uuid4(), tenant_id=tenant_id)
    seen: list[object] = []

    class _S:
        async def get(self, model: object, key: object) -> object | None:
            return call if model is knowledge.Call else None

    async def fake_chunks(session: object, got_call: object, got_tenant: object) -> None:
        seen.append(got_call)

    monkeypatch.setattr(knowledge, "_index_transcript_chunks", fake_chunks)

    await knowledge.index_call(_S(), tenant_id, call.id)  # type: ignore[arg-type]

    assert seen == [call]


@pytest.mark.asyncio
async def test_backfill_also_selects_calls_without_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[str] = []
    tenant_id = uuid4()
    call_id = uuid4()

    @asynccontextmanager
    async def fake_scope(tid: object = None, **kwargs: object):
        class _S:
            async def execute(self, statement: object, params: object = None) -> _Result:
                sql = str(statement)
                captured.append(sql)
                return _Result(call_id if "i.summary IS NULL" in sql else None)

        yield _S()

    async def fake_models(session: object) -> dict[str, str]:
        return {
            "embedding_provider": "aiservice",
            "embedding_model": "m",
            "ninerouter_embedding_model": "",
        }

    async def fake_tenants() -> list[object]:
        return [tenant_id]

    indexed: list[object] = []

    async def fake_index(session: object, tid: object, cid: object) -> None:
        indexed.append(cid)

    monkeypatch.setattr(knowledge, "session_scope", fake_scope)
    monkeypatch.setattr(knowledge, "effective_models", fake_models)
    monkeypatch.setattr(knowledge, "operational_tenant_ids", fake_tenants)
    monkeypatch.setattr(knowledge, "index_call", fake_index)

    assert (await knowledge.backfill_next()).startswith("indexed:")
    assert indexed == [call_id]
    assert len(captured) == 2
