from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.services.apache_age import execute_cypher


@pytest.mark.asyncio
async def test_non_superuser_can_use_age_across_fresh_connections() -> None:
    database_url = os.getenv("AGE_INTEGRATION_DATABASE_URL")
    if not database_url:
        pytest.skip("AGE_INTEGRATION_DATABASE_URL is not configured")

    engine = create_async_engine(database_url, pool_size=1, max_overflow=0)
    call_id = str(uuid4())
    tenant_id = str(uuid4())
    try:
        async with engine.connect() as connection:
            is_superuser = (
                await connection.execute(
                    text(
                        "SELECT rolsuper FROM pg_roles "
                        "WHERE rolname = current_user"
                    )
                )
            ).scalar_one()
            assert is_superuser is False
            await execute_cypher(
                connection,
                f'MERGE (c:Call {{id: "{call_id}"}}) '
                f'SET c.tenant_id = "{tenant_id}" RETURN c.id',
                ("call_id",),
            )
            await connection.commit()

        await engine.dispose()
        engine = create_async_engine(database_url, pool_size=1, max_overflow=0)
        async with engine.connect() as connection:
            rows = await execute_cypher(
                connection,
                f'MATCH (c:Call {{id: "{call_id}"}}) RETURN c.tenant_id',
                ("tenant_id",),
            )
            assert tenant_id in str(rows[0][0])
            await execute_cypher(
                connection,
                f'MATCH (c:Call {{id: "{call_id}"}}) DETACH DELETE c RETURN 1',
                ("result",),
            )
            await connection.commit()
    finally:
        await engine.dispose()
