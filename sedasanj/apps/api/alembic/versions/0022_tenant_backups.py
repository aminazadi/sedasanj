"""Add tenant backup registry.

Revision ID: 0022_tenant_backups
Revises: 0021_identity_projection_outbox
"""

from alembic import op

revision = "0022_tenant_backups"
down_revision = "0021_identity_projection_outbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE tenant_backups (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            status varchar(24) NOT NULL DEFAULT 'running',
            object_key text,
            checksum_sha256 varchar(64),
            size_bytes bigint,
            schema_revision varchar(128),
            error_detail text,
            started_at timestamptz NOT NULL DEFAULT now(),
            completed_at timestamptz,
            expires_at timestamptz,
            CONSTRAINT tenant_backups_status_check
              CHECK (status IN ('running','succeeded','failed','expired'))
        )
    """)
    op.execute("""
        CREATE INDEX idx_tenant_backups_tenant_started
          ON tenant_backups(tenant_id, started_at DESC)
    """)
    op.execute("REVOKE ALL ON tenant_backups FROM PUBLIC")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON tenant_backups TO cbi_app")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS tenant_backups")
