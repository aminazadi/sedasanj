from __future__ import annotations

from typing import Any

import pytest

from app.services import knowledge
from app.services.apache_age import ApacheAgeNotReadyError, assert_age_ready, execute_cypher


class _Result:
    def __init__(self, *, scalar: object = None, values: list[str] | None = None) -> None:
        self.scalar = scalar
        self.values = values or []

    def scalar_one(self) -> object:
        return self.scalar

    def scalar_one_or_none(self) -> object:
        return self.scalar

    def scalars(self) -> list[str]:
        return self.values

    def all(self) -> list[tuple[object, ...]]:
        return [(1,)]


class _Executor:
    def __init__(
        self,
        *,
        extensions: list[str] | None = None,
        cypher_error: Exception | None = None,
    ) -> None:
        self.extensions = extensions or ["vector", "age"]
        self.cypher_error = cypher_error
        self.statements: list[str] = []
        self.statement_parameters: list[dict[str, object]] = []

    async def execute(self, statement: object, params: Any = None) -> _Result:
        sql = str(statement)
        self.statements.append(sql)
        self.statement_parameters.append(dict(statement.compile().params))
        if "FROM pg_extension" in sql:
            return _Result(values=self.extensions)
        if "FROM ag_catalog.ag_graph" in sql:
            return _Result(scalar=1)
        if "ag_catalog.cypher" in sql and self.cypher_error is not None:
            raise self.cypher_error
        return _Result()


@pytest.mark.asyncio
async def test_age_readiness_checks_extensions_graph_and_cypher() -> None:
    executor = _Executor()

    await assert_age_ready(executor)

    assert any("set_config('search_path'" in sql for sql in executor.statements)
    assert any("FROM pg_extension" in sql for sql in executor.statements)
    assert any("FROM ag_catalog.ag_graph" in sql for sql in executor.statements)
    assert any("RETURN 1" in sql for sql in executor.statements)
    assert not any("shared_preload_libraries" in sql for sql in executor.statements)


@pytest.mark.asyncio
async def test_age_readiness_rejects_missing_extension() -> None:
    with pytest.raises(ApacheAgeNotReadyError, match="extension is not installed"):
        await assert_age_ready(_Executor(extensions=["vector"]))


@pytest.mark.asyncio
async def test_unhandled_cypher_error_has_actionable_message() -> None:
    executor = _Executor(cypher_error=RuntimeError("unhandled cypher(cstring) function call"))

    with pytest.raises(ApacheAgeNotReadyError, match="not loaded"):
        await execute_cypher(executor, "RETURN 1", ("result",))


@pytest.mark.asyncio
async def test_cypher_labels_are_not_parsed_as_sqlalchemy_bind_parameters() -> None:
    executor = _Executor()

    await execute_cypher(
        executor,
        "MATCH (c:Call)-[:HAS_TOPIC]->(t:Topic) RETURN c.id",
        ("call_id",),
    )

    statement = executor.statements[-1]
    assert ":Call" in statement
    assert ":HAS_TOPIC" in statement
    assert executor.statement_parameters[-1] == {}


@pytest.mark.parametrize(
    ("detail", "expected"),
    [
        (None, None),
        ("graph: old failure", None),
        ("vector: provider failed; graph: old failure", "vector: provider failed"),
        ("vector: provider failed", "vector: provider failed"),
    ],
)
def test_graph_retry_preserves_only_non_graph_errors(
    detail: str | None, expected: str | None
) -> None:
    assert knowledge._without_graph_error(detail) == expected
