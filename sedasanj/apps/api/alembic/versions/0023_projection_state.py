"""Add tenant identity projection state.

Revision ID: 0023_projection_state
Revises: 0022_tenant_backups
"""

from alembic import op

revision = "0023_projection_state"
down_revision = "0022_tenant_backups"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE identity_projection_state (
            tenant_id uuid NOT NULL,
            user_id uuid NOT NULL,
            version bigint NOT NULL,
            applied_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, user_id)
        )
    """)
    op.execute("REVOKE ALL ON identity_projection_state FROM PUBLIC")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON identity_projection_state TO cbi_app"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS identity_projection_state")
