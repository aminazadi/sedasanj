"""Initialize fixed knowledge graph labels for runtime roles.

Revision ID: 0038_initialize_knowledge_graph_labels
Revises: 0037_repair_apache_age_runtime
"""

from typing import Any

from sqlalchemy import text

from alembic import op

revision = "0038_initialize_knowledge_graph_labels"
down_revision = "0037_repair_apache_age_runtime"
branch_labels = None
depends_on = None

VERTEX_LABELS = ("Call", "Operator", "Topic", "Sentiment")
EDGE_LABELS = ("HANDLED", "HAS_TOPIC", "EXPRESSED")


def _label_exists(bind: Any, label: str) -> bool:
    return (
        bind.execute(
            text(
                "SELECT 1 FROM ag_catalog.ag_label AS label "
                "JOIN ag_catalog.ag_graph AS graph ON graph.graphid = label.graph "
                "WHERE graph.name = 'tenant_graph' AND label.name = :label"
            ),
            {"label": label},
        ).scalar_one_or_none()
        is not None
    )


def upgrade() -> None:
    bind = op.get_bind()
    for label in VERTEX_LABELS:
        if not _label_exists(bind, label):
            bind.execute(
                text("SELECT ag_catalog.create_vlabel('tenant_graph', :label)"),
                {"label": label},
            )
    for label in EDGE_LABELS:
        if not _label_exists(bind, label):
            bind.execute(
                text("SELECT ag_catalog.create_elabel('tenant_graph', :label)"),
                {"label": label},
            )

    for statement in (
        "GRANT USAGE, CREATE ON SCHEMA tenant_graph TO cbi_app",
        "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA tenant_graph TO cbi_app",
        "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA tenant_graph TO cbi_app",
        "ALTER DEFAULT PRIVILEGES IN SCHEMA tenant_graph GRANT SELECT, INSERT, "
        "UPDATE, DELETE ON TABLES TO cbi_app",
        "ALTER DEFAULT PRIVILEGES IN SCHEMA tenant_graph GRANT USAGE, SELECT ON "
        "SEQUENCES TO cbi_app",
    ):
        bind.execute(text(statement))


def downgrade() -> None:
    pass
