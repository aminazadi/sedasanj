from __future__ import annotations

import re
from typing import Any

from sqlalchemy import text

GRAPH_NAME = "tenant_graph"
_COLUMN_NAME = re.compile(r"^[a-z][a-z0-9_]*$")


class ApacheAgeNotReadyError(RuntimeError):
    pass


def _cypher_sql(query: str, columns: tuple[str, ...]) -> str:
    if not columns or any(not _COLUMN_NAME.fullmatch(column) for column in columns):
        raise ValueError("invalid Apache AGE result columns")
    delimiter = "$cbi_age$"
    if delimiter in query:
        raise ValueError("invalid Apache AGE query delimiter")
    query = query.replace(":", r"\:")
    result_shape = ", ".join(f"{column} ag_catalog.agtype" for column in columns)
    return (
        f"SELECT * FROM ag_catalog.cypher('{GRAPH_NAME}', {delimiter}"
        f"{query}{delimiter}) AS ({result_shape})"
    )


async def execute_cypher(
    executor: Any, query: str, columns: tuple[str, ...]
) -> list[Any]:
    try:
        await executor.execute(
            text(
                "SELECT set_config('search_path', "
                "'ag_catalog, \"$user\", public', true)"
            )
        )
        result = await executor.execute(text(_cypher_sql(query, columns)))
    except Exception as exc:
        if "unhandled cypher" in str(exc).lower():
            raise ApacheAgeNotReadyError(
                "Apache AGE runtime is not loaded on this database connection"
            ) from exc
        raise RuntimeError(f"Apache AGE Cypher execution failed: {exc}") from exc
    return list(result.all())


async def assert_age_ready(executor: Any) -> None:
    try:
        extensions = set(
            (
                await executor.execute(
                    text(
                        "SELECT extname FROM pg_extension "
                        "WHERE extname IN ('vector', 'age')"
                    )
                )
            ).scalars()
        )
        if extensions != {"vector", "age"}:
            raise ApacheAgeNotReadyError("Apache AGE or pgvector extension is not installed")

        graph_exists = (
            await executor.execute(
                text(
                    "SELECT 1 FROM ag_catalog.ag_graph "
                    "WHERE name = :graph_name"
                ),
                {"graph_name": GRAPH_NAME},
            )
        ).scalar_one_or_none()
        if graph_exists is None:
            raise ApacheAgeNotReadyError("Apache AGE tenant graph is not initialized")

        await execute_cypher(executor, "RETURN 1", ("result",))
    except ApacheAgeNotReadyError:
        raise
    except Exception as exc:
        raise ApacheAgeNotReadyError("Apache AGE readiness check failed") from exc
