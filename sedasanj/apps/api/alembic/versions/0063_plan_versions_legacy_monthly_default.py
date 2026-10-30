"""Give the retired monthly plan columns a default so new plan versions can be inserted."""

from alembic import op

revision = "0063_plan_monthly_default"
down_revision = "0062_payment_gateways"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE plan_versions ALTER COLUMN monthly_price_toman SET DEFAULT 0")


def downgrade() -> None:
    op.execute("ALTER TABLE plan_versions ALTER COLUMN monthly_price_toman DROP DEFAULT")
