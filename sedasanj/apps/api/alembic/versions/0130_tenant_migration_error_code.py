"""Stable error code for failed tenant database migrations.

The admin page shows the code with a Persian message and next action instead of raw exception
text (SQL, bound parameters).
"""

from alembic import op

revision = "0130_tenant_migration_error_code"
down_revision = "0129_payment_attempt_ref_unique"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE tenant_data_migrations ADD COLUMN IF NOT EXISTS error_code varchar(48)")
    op.execute(
        "ALTER TABLE tenant_provisioning_jobs ADD COLUMN IF NOT EXISTS error_code varchar(48)"
    )
    # Rows written by older code hold raw exception text (SQL and parameters); keep only the
    # first line so the page stays readable. The next retry rewrites them with a code.
    op.execute(
        "UPDATE tenant_data_migrations SET error_detail = left(split_part(error_detail, "
        "'[SQL:', 1), 500) WHERE error_detail LIKE '%[SQL:%'"
    )
    op.execute(
        "UPDATE tenant_provisioning_jobs SET error_detail = left(split_part(error_detail, "
        "'[SQL:', 1), 500) WHERE error_detail LIKE '%[SQL:%'"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE tenant_provisioning_jobs DROP COLUMN IF EXISTS error_code")
    op.execute("ALTER TABLE tenant_data_migrations DROP COLUMN IF EXISTS error_code")
