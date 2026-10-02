from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.routers import assistant
from app.services import knowledge


class _Rows:
    def __init__(self, rows: list[SimpleNamespace]) -> None:
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)


class _Session:
    def __init__(self, rows: list[SimpleNamespace]) -> None:
        self.rows = rows
        self.statement = None
        self.params = None

    async def execute(self, statement, params):
        self.statement = statement
        self.params = params
        return _Rows(self.rows)


@pytest.mark.asyncio
async def test_vector_call_context_returns_only_indexed_summary(monkeypatch) -> None:
    tenant_id = uuid4()
    call_id = uuid4()
    started_at = datetime(2026, 10, 2, tzinfo=UTC)
    session = _Session(
        [SimpleNamespace(call_id=call_id, started_at=started_at, summary="خلاصه برداری")]
    )

    async def fake_embed(content: str):
        assert content == "پرسش"
        return [0.1, 0.2], "embed-model"

    monkeypatch.setattr(knowledge, "embed", fake_embed)

    rows = await knowledge.vector_call_context(
        session, tenant_id, "پرسش", 5, None
    )

    assert rows == [
        {"call_id": call_id, "started_at": started_at, "summary": "خلاصه برداری"}
    ]
    sql = str(session.statement)
    assert "call_knowledge" in sql
    assert "transcripts" not in sql
    assert "to_tsvector" not in sql
    assert session.params["model"] == "embed-model"


@pytest.mark.asyncio
async def test_assistant_sources_use_only_vector_context(monkeypatch) -> None:
    tenant_id = uuid4()
    call_id = uuid4()
    started_at = datetime(2026, 10, 2, tzinfo=UTC)
    principal = SimpleNamespace(id=uuid4(), kind="user", role="org_admin")

    async def fake_vector_context(*args):
        return [
            {
                "call_id": call_id,
                "started_at": started_at,
                "summary": "تنها محتوای مجاز",
            }
        ]

    monkeypatch.setattr(knowledge, "vector_call_context", fake_vector_context)

    sources, context = await assistant._sources(
        object(), tenant_id, None, "پرسش", 10, principal
    )

    assert sources[0]["summary"] == "تنها محتوای مجاز"
    assert "تنها محتوای مجاز" in context
    assert "متن:" not in context
    assert "آمار جاری سازمان" not in context
    assert "روابط گراف دانش" not in context


@pytest.mark.asyncio
async def test_assistant_sources_do_not_fall_back_when_vector_search_fails(
    monkeypatch,
) -> None:
    principal = SimpleNamespace(id=uuid4(), kind="user", role="org_admin")

    async def failed_vector_context(*args):
        raise RuntimeError("embedding unavailable")

    monkeypatch.setattr(knowledge, "vector_call_context", failed_vector_context)

    sources, context = await assistant._sources(
        object(), uuid4(), None, "پرسش", 10, principal
    )

    assert sources == []
    assert context == ""
