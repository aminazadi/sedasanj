"""Track idempotency and the previous plan on subscription changes."""

from alembic import op

revision = "0065_sub_change_idempotency"
down_revision = "0064_money_bigint"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE subscription_changes ADD COLUMN idempotency_key varchar(128)")
    op.execute("ALTER TABLE subscription_changes ADD COLUMN request_hash varchar(64)")
    op.execute("ALTER TABLE subscription_changes ADD COLUMN previous_plan_version_id uuid")
    op.execute("ALTER TABLE subscription_changes ADD COLUMN previous_extra_operators integer")
    op.execute(
        "CREATE UNIQUE INDEX subscription_changes_tenant_idem_key "
        "ON subscription_changes (tenant_id, idempotency_key) WHERE idempotency_key IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS subscription_changes_tenant_idem_key")
    op.execute("ALTER TABLE subscription_changes DROP COLUMN previous_extra_operators")
    op.execute("ALTER TABLE subscription_changes DROP COLUMN previous_plan_version_id")
    op.execute("ALTER TABLE subscription_changes DROP COLUMN request_hash")
    op.execute("ALTER TABLE subscription_changes DROP COLUMN idempotency_key")
