"""Add the product dimension (sedasanj / jalase_negar), signup channel and the free JN plan."""

from alembic import op

revision = "0145_product_and_signup_channel"
down_revision = "0144_site_scripts_help"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE tenants ADD COLUMN product varchar(32) NOT NULL DEFAULT 'sedasanj'")
    op.execute(
        "ALTER TABLE tenants ADD CONSTRAINT tenants_product_check "
        "CHECK (product IN ('sedasanj','jalase_negar'))"
    )
    op.execute("ALTER TABLE tenants ADD COLUMN signup_channel varchar(32)")
    op.execute("CREATE INDEX tenants_product_idx ON tenants (product)")
    op.execute("ALTER TABLE users ADD COLUMN signup_channel varchar(32)")
    op.execute("ALTER TABLE plans ADD COLUMN product varchar(32) NOT NULL DEFAULT 'sedasanj'")
    op.execute(
        "ALTER TABLE plans ADD CONSTRAINT plans_product_check "
        "CHECK (product IN ('sedasanj','jalase_negar'))"
    )
    op.execute("CREATE INDEX plans_product_idx ON plans (product)")
    # The permanent free plan: never sold, assigned at sign-up. `intro_minutes` is the monthly
    # free allowance, granted again every month by plan_credit.ensure_period_credit.
    op.execute(
        "INSERT INTO plans (code, name, active, public, is_trial, sellable, sort_order, product) "
        "VALUES ('jn_free', 'جلسه‌نگار رایگان', true, false, false, false, 0, 'jalase_negar') "
        "ON CONFLICT (code) DO NOTHING"
    )
    op.execute(
        "INSERT INTO plan_versions (plan_id, version, monthly_price_toman, annual_price_toman, "
        "base_operators, intro_minutes, overage_price_per_minute_toman, assistant_tier, "
        "assistant_monthly_messages, assistant_source_limit, status, effective_at, published_at) "
        "SELECT id, 1, 0, NULL, 1, 60, 2000, 'demo', 0, 0, 'published', now(), now() "
        "FROM plans WHERE code = 'jn_free' "
        "AND NOT EXISTS (SELECT 1 FROM plan_versions pv WHERE pv.plan_id = plans.id)"
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM plan_versions WHERE plan_id IN (SELECT id FROM plans WHERE code = 'jn_free')"
    )
    op.execute("DELETE FROM plans WHERE code = 'jn_free'")
    op.execute("DROP INDEX IF EXISTS plans_product_idx")
    op.execute("ALTER TABLE plans DROP CONSTRAINT IF EXISTS plans_product_check")
    op.execute("ALTER TABLE plans DROP COLUMN IF EXISTS product")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS signup_channel")
    op.execute("DROP INDEX IF EXISTS tenants_product_idx")
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS signup_channel")
    op.execute("ALTER TABLE tenants DROP CONSTRAINT IF EXISTS tenants_product_check")
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS product")
