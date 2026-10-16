"""Publish annual plan pricing and prepare plan controlled monthly usage."""

from alembic import op

revision = "0051_annual_plan_monthly_quotas"
down_revision = "0050_scheduled_reports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE credit_reservations ADD COLUMN price_per_minute_toman integer NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE credit_reservations ADD COLUMN free_seconds integer NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE plan_versions DROP CONSTRAINT IF EXISTS plan_versions_nonnegative_check")
    op.execute(
        "ALTER TABLE plan_versions ADD CONSTRAINT plan_versions_nonnegative_check "
        "CHECK (monthly_price_toman >= 0 AND base_operators >= 0 AND intro_minutes >= 0)"
    )
    op.execute(
        "ALTER TABLE plan_versions ADD CONSTRAINT plan_versions_annual_price_nonnegative_check "
        "CHECK (annual_price_toman IS NULL OR annual_price_toman >= 0)"
    )
    op.execute("""
        WITH latest AS (
            SELECT DISTINCT ON (plan_id) id, plan_id, version FROM plan_versions
            WHERE status = 'published' ORDER BY plan_id, effective_at DESC NULLS LAST, version DESC
        ), replacements AS (
            SELECT p.id AS plan_id, p.code, l.version + 1 AS version,
                0 AS monthly_price_toman,
                CASE p.code WHEN 'bronze' THEN 9900000 WHEN 'silver' THEN 29900000
                    WHEN 'gold' THEN 59900000 ELSE pv.annual_price_toman END AS annual_price_toman,
                pv.base_operators, pv.intro_minutes,
                CASE p.code WHEN 'demo' THEN 7000 WHEN 'bronze' THEN 6000
                    WHEN 'silver' THEN 5000 WHEN 'gold' THEN 4000
                    ELSE pv.overage_price_per_minute_toman END AS overage_price_per_minute_toman,
                pv.assistant_tier, pv.assistant_monthly_messages, pv.assistant_source_limit,
                pv.assistant_model, pv.allows_extra_operators,
                NULL::integer AS extra_operator_monthly_toman,
                pv.extra_operator_annual_toman, pv.trial_days
            FROM plans p JOIN latest l ON l.plan_id = p.id
            JOIN plan_versions pv ON pv.id = l.id
            WHERE p.code IN ('demo','bronze','silver','gold')
        )
        INSERT INTO plan_versions(plan_id,version,monthly_price_toman,annual_price_toman,
            base_operators,intro_minutes,overage_price_per_minute_toman,assistant_tier,
            assistant_monthly_messages,assistant_source_limit,assistant_model,
            allows_extra_operators,extra_operator_monthly_toman,extra_operator_annual_toman,
            trial_days,status,effective_at,published_at)
        SELECT plan_id,version,monthly_price_toman,annual_price_toman,base_operators,
            intro_minutes,overage_price_per_minute_toman,assistant_tier,
            assistant_monthly_messages,assistant_source_limit,assistant_model,
            allows_extra_operators,extra_operator_monthly_toman,extra_operator_annual_toman,
            trial_days,'published',now(),now() FROM replacements
    """)
    op.execute("""
        UPDATE subscriptions s SET plan_version_id = newer.id,
            price_per_minute_toman = newer.overage_price_per_minute_toman,
            assistant_tier = newer.assistant_tier,
            assistant_monthly_messages = newer.assistant_monthly_messages,
            assistant_source_limit = newer.assistant_source_limit,
            assistant_model = newer.assistant_model
        FROM plan_versions old
        JOIN plans p ON p.id = old.plan_id
        JOIN plan_versions newer ON newer.plan_id = old.plan_id AND newer.version = old.version + 1
        WHERE s.plan_version_id = old.id AND old.status = 'published'
          AND p.code IN ('demo','bronze','silver','gold')
          AND s.status IN ('expired','active','trialing')
          AND s.period_end <= now()
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE plan_versions DROP CONSTRAINT IF EXISTS plan_versions_nonnegative_check")
    op.execute(
        "ALTER TABLE plan_versions ADD CONSTRAINT plan_versions_nonnegative_check "
        "CHECK (monthly_price_toman >= 0 AND base_operators >= 0 AND intro_minutes >= 0)"
    )
    op.execute(
        "ALTER TABLE plan_versions DROP CONSTRAINT IF EXISTS "
        "plan_versions_annual_price_nonnegative_check"
    )
    op.execute("""
        UPDATE subscriptions s SET plan_version_id = old.id
        FROM plan_versions newer JOIN plans p ON p.id = newer.plan_id
        JOIN plan_versions old ON old.plan_id = newer.plan_id AND old.version = newer.version - 1
        WHERE s.plan_version_id = newer.id AND p.code IN ('demo','bronze','silver','gold')
    """)
    op.execute("""
        DELETE FROM plan_versions newer USING plans p
        WHERE newer.plan_id = p.id AND p.code IN ('demo','bronze','silver','gold')
          AND newer.version = (SELECT max(x.version) FROM plan_versions x WHERE x.plan_id=p.id)
    """)
    op.execute("ALTER TABLE credit_reservations DROP COLUMN free_seconds")
    op.execute("ALTER TABLE credit_reservations DROP COLUMN price_per_minute_toman")
