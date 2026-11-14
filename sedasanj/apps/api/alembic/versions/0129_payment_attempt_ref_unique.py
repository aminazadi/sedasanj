"""One verified payment attempt per bank reference.

Stops a replayed bank callback from fulfilling a second order with the same bank reference.
"""

from alembic import op

revision = "0129_payment_attempt_ref_unique"
down_revision = "0128_help_categories_archive"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS payment_attempts_verified_ref_uq "
        "ON payment_attempts (gateway, ref_id) "
        "WHERE status = 'verified' AND ref_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS payment_attempts_verified_ref_uq")
