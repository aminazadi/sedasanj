"""On-demand tenant backups and stable backup error codes.

Adds the ``requested`` status (the backup worker picks these up before scheduled ones) and an
``error_code`` column so the admin page can show what failed and what to do next.
"""

from alembic import op

revision = "0134_tenant_backup_requests"
down_revision = "0133_sms_templates_deliveries"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE tenant_backups ADD COLUMN IF NOT EXISTS error_code varchar(48)")
    op.execute("ALTER TABLE tenant_backups DROP CONSTRAINT IF EXISTS tenant_backups_status_check")
    op.execute(
        "ALTER TABLE tenant_backups ADD CONSTRAINT tenant_backups_status_check "
        "CHECK (status IN ('requested','running','succeeded','failed','expired'))"
    )


def downgrade() -> None:
    op.execute("DELETE FROM tenant_backups WHERE status = 'requested'")
    op.execute("ALTER TABLE tenant_backups DROP CONSTRAINT IF EXISTS tenant_backups_status_check")
    op.execute(
        "ALTER TABLE tenant_backups ADD CONSTRAINT tenant_backups_status_check "
        "CHECK (status IN ('running','succeeded','failed','expired'))"
    )
    op.execute("ALTER TABLE tenant_backups DROP COLUMN IF EXISTS error_code")
