"""Add plan sellability flags and constrain credit grant sources."""

from alembic import op

revision = "0067_plan_flags_grant_check"
down_revision = "0066_invoice_tax_breakdown"
branch_labels = None
depends_on = None

_SOURCES = "'monthly_plan','credit_purchase','prepaid','legacy','admin_adjustment','intro_bonus'"


def upgrade() -> None:
    op.execute("ALTER TABLE plans ADD COLUMN is_trial boolean NOT NULL DEFAULT false")
    op.execute("ALTER TABLE plans ADD COLUMN sellable boolean NOT NULL DEFAULT true")
    op.execute("UPDATE plans SET is_trial = true, sellable = false WHERE code = 'demo'")
    op.execute("UPDATE plans SET sellable = false WHERE code = 'legacy_custom'")
    # NOT VALID: new rows are checked without scanning historical grants on deploy.
    op.execute(
        "ALTER TABLE credit_grants ADD CONSTRAINT credit_grants_source_check "
        f"CHECK (source IN ({_SOURCES})) NOT VALID"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE credit_grants DROP CONSTRAINT IF EXISTS credit_grants_source_check")
    op.execute("ALTER TABLE plans DROP COLUMN sellable")
    op.execute("ALTER TABLE plans DROP COLUMN is_trial")
