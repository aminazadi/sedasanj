from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from app.services import org_knowledge


class _Result:
    def __init__(self, value: object = None) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object:
        return self._value


class _Session:
    def __init__(self, complete: object = None) -> None:
        self.complete = complete
        self.statements: list[str] = []

    async def execute(self, statement: object, params: dict[str, object] | None = None):
        sql = str(statement)
        self.statements.append(sql)
        return _Result(self.complete if "bool_and" in sql else None)

    def begin_nested(self):
        session = self

        class _Ctx:
            async def __aenter__(self) -> None:
                return None

            async def __aexit__(self, *exc: object) -> None:
                return None

        del session
        return _Ctx()


def _row(content: str = "alpha beta") -> SimpleNamespace:
    return SimpleNamespace(
        source_id=uuid4(), call_id=None, access="tenant", title="t", content=content, updated_at=1
    )


def test_every_source_query_is_tenant_scoped_and_complete() -> None:
    assert len({source.source_type for source in org_knowledge.SOURCES}) == len(
        org_knowledge.SOURCES
    )
    for source in org_knowledge.SOURCES:
        assert ":tenant_id" in source.query
        for column in ("source_id", "call_id", "access", "title", "content", "updated_at"):
            assert column in source.query


def test_contacts_and_reports_are_admin_only() -> None:
    access = {s.source_type: ("'admin' AS access" in s.query) for s in org_knowledge.SOURCES}
    assert access["contact"] and access["scheduled_report"]


def test_operator_search_is_limited_to_own_calls_and_call_scoped_chunks() -> None:
    principal = SimpleNamespace(
        kind="user",
        role="operator",
        id=uuid4(),
        tenant_id=uuid4(),
        mobile_number=None,
        extension=None,
    )
    stmt = org_knowledge.search_statement(
        principal, query_vector=[0.1, 0.2], model="m", source_types=None, limit=5
    )
    compiled = stmt.compile(dialect=postgresql.dialect())
    assert "call_operator_assignments" in str(compiled)
    assert "org_knowledge_chunks.access IN" in str(compiled)
    assert ["call"] in compiled.params.values()
    assert not any(isinstance(v, list) and "admin" in v for v in compiled.params.values())


@pytest.mark.parametrize(("role", "expects_admin"), [("org_admin", True), ("manager", False)])
def test_only_org_admin_can_read_admin_chunks(role: str, expects_admin: bool) -> None:
    levels = org_knowledge._access_levels(role, operator=False)
    assert ("admin" in levels) is expects_admin


@pytest.mark.asyncio
async def test_failed_embedding_keeps_complete_vectors(monkeypatch: pytest.MonkeyPatch) -> None:
    async def broken(content: str) -> tuple[list[float], str]:
        raise RuntimeError("down")

    monkeypatch.setattr(org_knowledge, "embed", broken)
    session = _Session(complete=True)

    result = await org_knowledge.index_source_row(
        session,
        uuid4(),
        org_knowledge.SOURCES[0],
        _row(),  # type: ignore[arg-type]
    )

    assert result == "kept"
    assert not any(s.startswith("DELETE FROM org_knowledge_chunks") for s in session.statements)


@pytest.mark.asyncio
async def test_new_source_row_with_failed_embedding_gets_retry_placeholder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def broken(content: str) -> tuple[list[float], str]:
        raise RuntimeError("down")

    monkeypatch.setattr(org_knowledge, "embed", broken)
    session = _Session(complete=None)

    result = await org_knowledge.index_source_row(
        session,
        uuid4(),
        org_knowledge.SOURCES[0],
        _row(),  # type: ignore[arg-type]
    )

    assert result == "failed"
    assert any(
        "'failed'" in s and s.startswith("INSERT INTO org_knowledge_chunks")
        for s in session.statements
    )


@pytest.mark.asyncio
async def test_successful_row_is_embedded_and_stored(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_embed(content: str) -> tuple[list[float], str]:
        return [0.1, 0.2], "model-x"

    monkeypatch.setattr(org_knowledge, "embed", fake_embed)
    session = _Session()

    result = await org_knowledge.index_source_row(
        session,
        uuid4(),
        org_knowledge.SOURCES[0],
        _row(),  # type: ignore[arg-type]
    )

    assert result == "ready"
    assert any(
        "'ready'" in s and s.startswith("INSERT INTO org_knowledge_chunks")
        for s in session.statements
    )


def test_merge_coverage_sums_sources() -> None:
    one = {"team": {"total": 2, "ready": 1, "pending": 1}}
    two = {
        "team": {"total": 3, "ready": 3, "pending": 0},
        "contact": {"total": 1, "ready": 0, "pending": 1},
    }
    merged = org_knowledge.merge_coverage([one, two])
    assert merged["team"] == {"total": 5, "ready": 4, "pending": 1}
    assert merged["contact"]["pending"] == 1
