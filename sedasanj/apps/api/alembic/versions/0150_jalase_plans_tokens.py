"""Jalase-Negar paid plans, a token cap on the free plan and product-scoped token packs.

Plan prices (toman, monthly) are the product owner's; the token allowances and pack sizes are
starting guesses (one hour of meeting is roughly 40k tokens across its documents) that the admin
Plans and Token packs pages edit once real usage is known.
"""

from alembic import op

revision = "0150_jalase_plans_tokens"
down_revision = "0149_meeting_documents"
branch_labels = None
depends_on = None

# code, name, sort_order, monthly price (toman), monthly tokens, monthly minutes
PLANS = (
    ("jn_bronze", "جلسه‌نگار برنزی", 10, 280_000, 800_000, 1_200),
    ("jn_silver", "جلسه‌نگار نقره‌ای", 20, 480_000, 1_600_000, 2_400),
    ("jn_gold", "جلسه‌نگار طلایی", 30, 680_000, 3_200_000, 4_800),
)
FREE_TOKENS = 120_000
PACKS = (
    ("بستهٔ ۱۵۰ هزار توکنی", 150_000, 60_000),
    ("بستهٔ ۴۰۰ هزار توکنی", 400_000, 160_000),
    ("بستهٔ ۱ میلیون توکنی", 1_000_000, 400_000),
)


def upgrade() -> None:
    op.execute(
        "ALTER TABLE token_packages ADD COLUMN product varchar(32) NOT NULL DEFAULT 'sedasanj'"
    )
    op.execute(
        "ALTER TABLE token_packages ADD CONSTRAINT token_packages_product_check "
        "CHECK (product IN ('sedasanj','jalase_negar'))"
    )
    op.execute("CREATE INDEX token_packages_product_idx ON token_packages (product)")
    # NULL meant "unlimited": the free plan must have a real monthly allowance.
    op.execute(
        f"UPDATE plan_versions SET llm_monthly_tokens = {FREE_TOKENS} "
        "WHERE plan_id IN (SELECT id FROM plans WHERE code = 'jn_free') "
        "AND llm_monthly_tokens IS NULL"
    )
    op.execute(
        f"UPDATE subscriptions SET llm_monthly_tokens = {FREE_TOKENS} "
        "WHERE llm_monthly_tokens IS NULL AND plan_version_id IN ("
        "SELECT pv.id FROM plan_versions pv JOIN plans p ON p.id = pv.plan_id "
        "WHERE p.code = 'jn_free')"
    )
    for code, name, order, price, tokens, minutes in PLANS:
        op.execute(
            "INSERT INTO plans (code, name, active, public, is_trial, sellable, sort_order, "
            f"product) VALUES ('{code}', '{name}', true, true, false, true, {order}, "
            "'jalase_negar') ON CONFLICT (code) DO NOTHING"
        )
        op.execute(
            "INSERT INTO plan_versions (plan_id, version, monthly_price_toman, annual_price_toman, "
            "base_operators, intro_minutes, overage_price_per_minute_toman, assistant_tier, "
            "assistant_monthly_messages, assistant_source_limit, llm_monthly_tokens, status, "
            f"effective_at, published_at) SELECT id, 1, {price}, NULL, 1, {minutes}, 2000, "
            f"'demo', 0, 0, {tokens}, 'published', now(), now() FROM plans WHERE code = '{code}' "
            "AND NOT EXISTS (SELECT 1 FROM plan_versions pv WHERE pv.plan_id = plans.id)"
        )
    for name, tokens, price in PACKS:
        op.execute(
            "INSERT INTO token_packages (name, tokens, price_toman, active, product) "
            f"VALUES ('{name}', {tokens}, {price}, true, 'jalase_negar')"
        )


def downgrade() -> None:
    op.execute("DELETE FROM token_packages WHERE product = 'jalase_negar'")
    codes = ",".join(f"'{plan[0]}'" for plan in PLANS)
    op.execute(
        f"DELETE FROM plan_versions WHERE plan_id IN (SELECT id FROM plans WHERE code IN ({codes}))"
    )
    op.execute(f"DELETE FROM plans WHERE code IN ({codes})")
    op.execute(
        "UPDATE plan_versions SET llm_monthly_tokens = NULL "
        "WHERE plan_id IN (SELECT id FROM plans WHERE code = 'jn_free')"
    )
    op.execute("DROP INDEX IF EXISTS token_packages_product_idx")
    op.execute("ALTER TABLE token_packages DROP CONSTRAINT IF EXISTS token_packages_product_check")
    op.execute("ALTER TABLE token_packages DROP COLUMN IF EXISTS product")
