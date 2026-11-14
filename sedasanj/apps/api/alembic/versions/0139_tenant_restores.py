"""Admin-driven tenant database restores.

A restore is staged from a verified backup into a scratch database, verified, and only then
swapped in after an explicit apply. Control-plane only (listed in ``_CONTROL_ONLY``).
"""

from alembic import op

revision = "0139_tenant_restores"
down_revision = "0138_token_packages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE tenant_restores (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            backup_id uuid REFERENCES tenant_backups(id) ON DELETE SET NULL,
            status varchar(24) NOT NULL DEFAULT 'requested',
            staging_database varchar(63),
            previous_database varchar(63),
            verification jsonb NOT NULL DEFAULT '{}',
            checkpoint jsonb NOT NULL DEFAULT '{}',
            error_code varchar(48),
            error_detail text,
            requested_by uuid,
            applied_by uuid,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            applied_at timestamptz,
            CONSTRAINT tenant_restores_status_check CHECK (status IN
              ('requested','staging','staged','apply_requested','applying',
               'applied','failed','cancelled'))
        )
    """)
    op.execute(
        "CREATE INDEX idx_tenant_restores_tenant_created ON tenant_restores(tenant_id, created_at)"
    )
    op.execute(
        "CREATE UNIQUE INDEX tenant_restores_one_active ON tenant_restores(tenant_id) "
        "WHERE status IN ('requested','staging','staged','apply_requested','applying')"
    )
    op.execute("REVOKE ALL ON tenant_restores FROM PUBLIC")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON tenant_restores TO cbi_app")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS tenant_restores")
