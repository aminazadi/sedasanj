"""Repair assistant embedding routing and graph initialization.

Revision ID: 0033_repair_assistant_indexes
Revises: 0032_repair_apache_age_graph
"""

from sqlalchemy import text

from alembic import op

revision = "0033_repair_assistant_indexes"
down_revision = "0032_repair_apache_age_graph"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    age_available = bind.execute(
        text("SELECT 1 FROM pg_available_extensions WHERE name = 'age'")
    ).scalar_one_or_none()
    if age_available is not None:
        bind.execute(text("CREATE EXTENSION IF NOT EXISTS age"))
        graph_exists = bind.execute(
            text("SELECT 1 FROM ag_catalog.ag_graph WHERE name = 'tenant_graph'")
        ).scalar_one_or_none()
        if graph_exists is None:
            bind.execute(text("SELECT ag_catalog.create_graph('tenant_graph')"))
        for statement in (
            "GRANT USAGE ON SCHEMA ag_catalog TO cbi_app",
            "GRANT SELECT ON ag_catalog.ag_graph TO cbi_app",
            "GRANT USAGE, CREATE ON SCHEMA tenant_graph TO cbi_app",
            "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA tenant_graph TO cbi_app",
            "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA tenant_graph TO cbi_app",
        ):
            bind.execute(text(statement))
    bind.execute(
        text(
            "UPDATE platform_settings SET value = 'native', updated_at = now() "
            "WHERE key = 'embedding_route' AND value = 'ninerouter'"
        )
    )


def downgrade() -> None:
    pass
