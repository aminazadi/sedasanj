"""Run against a disposable PostgreSQL database supplied explicitly by the test runner."""

# ruff: noqa: E501 - SQL statements are kept readable for this migration integration test.

import importlib.util
import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

URL = os.environ.get("PANEL_ACCESS_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="disposable PostgreSQL URL not supplied")


def migration(name):
    path = Path(__file__).parents[1] / "apps/api/alembic/versions" / name
    spec = importlib.util.spec_from_file_location(name[:-3], path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def apply(connection, module, direction):
    with Operations.context(MigrationContext.configure(connection)):
        getattr(module, direction)()


async def test_real_postgres_upgrade_primary_guards_and_downgrade():
    engine = create_async_engine(URL)
    schema = "panel_access_" + uuid4().hex
    modules = [
        migration(name)
        for name in [
            "0112_user_panel_permissions.py",
            "0113_user_panel_access_help.py",
            "0114_primary_organization_admin.py",
        ]
    ]
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            await connection.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
            await connection.execute(
                text(
                    "CREATE TABLE users (id uuid PRIMARY KEY, tenant_id uuid NOT NULL, role text NOT NULL, display_name text, created_at timestamptz NOT NULL DEFAULT now())"
                )
            )
            await connection.execute(
                text(
                    "CREATE TABLE help_articles (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), slug text UNIQUE, title text, summary text, body_html text, body_plain text, kind text, status text, published_at timestamptz)"
                )
            )
            await connection.execute(
                text(
                    "CREATE TABLE help_error_codes (code text PRIMARY KEY, article_id uuid, source text, severity text, title text, quick_action text)"
                )
            )
            tenant, owner, member = uuid4(), uuid4(), uuid4()
            await connection.execute(
                text(
                    "INSERT INTO users (id, tenant_id, role, created_at) VALUES (:owner, :tenant, 'org_admin', now() - interval '1 day'), (:member, :tenant, 'org_admin', now())"
                ),
                {"owner": owner, "member": member, "tenant": tenant},
            )
            for module in modules:
                await connection.run_sync(apply, module, "upgrade")
            rows = (
                await connection.execute(
                    text("SELECT id, is_primary_admin, panel_permissions FROM users")
                )
            ).all()
            assert {row.id: row.is_primary_admin for row in rows} == {owner: True, member: False}
            assert all(row.panel_permissions is None for row in rows)
            for statement in [
                "DELETE FROM users WHERE id = :owner",
                "UPDATE users SET role = 'viewer' WHERE id = :owner",
                "UPDATE users SET panel_permissions = '[]'::jsonb WHERE id = :owner",
                "UPDATE users SET is_primary_admin = false WHERE id = :owner",
                "UPDATE users SET tenant_id = :member WHERE id = :owner",
            ]:
                with pytest.raises(IntegrityError, match="primary_admin_protected"):
                    async with connection.begin_nested():
                        await connection.execute(
                            text(statement), {"owner": owner, "member": member}
                        )
            await connection.execute(
                text("UPDATE users SET display_name = 'Owner' WHERE id = :owner"), {"owner": owner}
            )
            await connection.execute(
                text("UPDATE users SET panel_permissions = '[]'::jsonb WHERE id = :member"),
                {"member": member},
            )
            assert (
                await connection.execute(
                    text("SELECT panel_permissions FROM users WHERE id = :member"),
                    {"member": member},
                )
            ).scalar_one() == []
            assert (
                await connection.execute(
                    text(
                        "SELECT count(*) FROM help_error_codes WHERE code IN ('panel_access_denied', 'primary_admin_protected')"
                    )
                )
            ).scalar_one() == 2
            await connection.run_sync(apply, modules[-1], "downgrade")
            assert (
                "data-primary-admin"
                not in (
                    await connection.execute(
                        text("SELECT body_html FROM help_articles WHERE slug = 'user-panel-access'")
                    )
                ).scalar_one()
            )
            await connection.run_sync(apply, modules[-1], "upgrade")
            for module in reversed(modules):
                await connection.run_sync(apply, module, "downgrade")
            columns = (
                (
                    await connection.execute(
                        text(
                            "SELECT column_name FROM information_schema.columns WHERE table_schema = :schema AND table_name = 'users'"
                        ),
                        {"schema": schema},
                    )
                )
                .scalars()
                .all()
            )
            assert "panel_permissions" not in columns and "is_primary_admin" not in columns
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    finally:
        await engine.dispose()
