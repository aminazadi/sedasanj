"""Forbid negative credit grant balances (enforced for new writes; old rows are not rescanned)."""

from alembic import op

revision = "0136_grant_balance_checks"
down_revision = "0135_sms_notifications_help"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE credit_grants ADD CONSTRAINT credit_grants_remaining_nonneg "
        "CHECK (remaining_seconds >= 0) NOT VALID"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE credit_grants DROP CONSTRAINT credit_grants_remaining_nonneg")
