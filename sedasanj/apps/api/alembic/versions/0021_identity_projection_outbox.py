"""Add durable identity projection outbox.

Revision ID: 0021_identity_projection_outbox
Revises: 0020_tenant_database_control_plane
"""

from alembic import op

revision = "0021_identity_projection_outbox"
down_revision = "0020_tenant_database_control_plane"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE identity_projection_outbox (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            user_id uuid NOT NULL,
            operation varchar(16) NOT NULL,
            version bigint NOT NULL,
            payload jsonb NOT NULL,
            attempt integer NOT NULL DEFAULT 0,
            available_at timestamptz NOT NULL DEFAULT now(),
            applied_at timestamptz,
            error_detail text,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT identity_projection_operation_check
              CHECK (operation IN ('upsert','delete')),
            CONSTRAINT identity_projection_version_key
              UNIQUE (tenant_id, user_id, version)
        )
    """)
    op.execute("""
        CREATE INDEX idx_identity_projection_pending
          ON identity_projection_outbox(applied_at, available_at, created_at)
    """)
    op.execute("REVOKE ALL ON identity_projection_outbox FROM PUBLIC")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON identity_projection_outbox TO cbi_app"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS identity_projection_outbox")
