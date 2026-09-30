"""Add controlled commerce administration and refunds.

Revision ID: 0019_admin_commerce_control
Revises: 0018_commerce_subscriptions
"""

from sqlalchemy import text

from alembic import context, op

revision = "0019_admin_commerce_control"
down_revision = "0018_commerce_subscriptions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if not context.is_offline_mode():
        duplicate = bind.execute(
            text(
                "SELECT tenant_id FROM subscriptions "
                "WHERE status IN ('active','trialing') GROUP BY tenant_id "
                "HAVING count(*) > 1 LIMIT 1"
            )
        ).scalar_one_or_none()
        if duplicate is not None:
            raise RuntimeError(
                "multiple active subscriptions must be resolved before commerce control migration"
            )

    op.execute("ALTER TABLE staff_users ADD COLUMN disabled_at timestamptz")
    op.execute("ALTER TABLE plan_versions ALTER COLUMN published_at DROP NOT NULL")
    op.execute("ALTER TABLE plan_versions ADD COLUMN status varchar(16) NOT NULL DEFAULT 'published'")
    op.execute("ALTER TABLE plan_versions ADD COLUMN effective_at timestamptz")
    op.execute("ALTER TABLE plan_versions ADD COLUMN retired_at timestamptz")
    op.execute("ALTER TABLE plan_versions ADD COLUMN created_by uuid REFERENCES staff_users(id) ON DELETE SET NULL")
    op.execute("UPDATE plan_versions SET status='published', effective_at=published_at")
    op.execute("ALTER TABLE plan_versions ADD CONSTRAINT plan_versions_status_check CHECK (status IN ('draft','published','retired'))")
    op.execute("CREATE UNIQUE INDEX subscriptions_one_live_per_tenant ON subscriptions(tenant_id) WHERE status IN ('active','trialing')")

    op.execute(
        """
        INSERT INTO subscriptions(
            tenant_id, plan_version_id, status, billing_period, period_start, period_end,
            base_operators, extra_operators, price_per_minute_toman, assistant_tier,
            assistant_monthly_messages, assistant_source_limit
        )
        SELECT t.id, pv.id, 'active', 'legacy', t.created_at, '9999-12-31T00:00:00Z',
               t.max_operators, 0, t.price_per_minute_toman, 'advanced', 2147483647, 50
        FROM tenants t
        JOIN plans p ON p.code='legacy_custom'
        JOIN plan_versions pv ON pv.plan_id=p.id AND pv.status='published'
        WHERE t.status <> 'deleted'
          AND NOT EXISTS (SELECT 1 FROM subscriptions s WHERE s.tenant_id=t.id)
        """
    )

    op.execute("ALTER TABLE contact_leads ADD COLUMN internal_notes text")
    op.execute("ALTER TABLE contact_leads ADD COLUMN follow_up_at timestamptz")
    op.execute("ALTER TABLE orders ADD CONSTRAINT orders_status_check CHECK (status IN ('draft','pending_payment','paid','canceled','partially_refunded','refunded'))")
    op.execute("ALTER TABLE payment_attempts ADD CONSTRAINT payment_attempts_status_check CHECK (status IN ('redirected','canceled','pending_verification','failed','verified'))")
    op.execute("ALTER TABLE subscription_changes ADD CONSTRAINT subscription_changes_status_check CHECK (status IN ('scheduled','pending_payment','applied','canceled','failed'))")
    op.execute("ALTER TABLE installation_requests ADD CONSTRAINT installation_requests_status_check CHECK (status IN ('requested','paid','reviewing','scheduled','in_progress','completed','canceled'))")
    op.execute(
        """
        CREATE TABLE refunds (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            order_id uuid NOT NULL REFERENCES orders(id),
            payment_attempt_id uuid REFERENCES payment_attempts(id),
            tenant_id uuid NOT NULL REFERENCES tenants(id),
            amount_toman integer NOT NULL CHECK (amount_toman > 0),
            status varchar(24) NOT NULL CHECK (status IN ('pending','completed','failed')),
            method varchar(24) NOT NULL CHECK (method IN ('reverse','manual')),
            reason text NOT NULL,
            idempotency_key varchar(128) NOT NULL,
            gateway_reference varchar(128),
            response_json jsonb NOT NULL DEFAULT '{}',
            created_by uuid REFERENCES staff_users(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            completed_at timestamptz,
            CONSTRAINT refunds_tenant_idem_key UNIQUE(tenant_id, idempotency_key)
        )
        """
    )
    op.execute("CREATE INDEX refunds_order_created_idx ON refunds(order_id, created_at DESC)")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON refunds TO cbi_app")
    op.execute("ALTER TABLE refunds ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE refunds FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY refunds_tenant_isolation ON refunds "
        "USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid "
        "OR current_setting('app.staff', true) = 'on') "
        "WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid "
        "OR current_setting('app.staff', true) = 'on')"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS refunds")
    op.execute("ALTER TABLE installation_requests DROP CONSTRAINT IF EXISTS installation_requests_status_check")
    op.execute("ALTER TABLE subscription_changes DROP CONSTRAINT IF EXISTS subscription_changes_status_check")
    op.execute("ALTER TABLE payment_attempts DROP CONSTRAINT IF EXISTS payment_attempts_status_check")
    op.execute("ALTER TABLE orders DROP CONSTRAINT IF EXISTS orders_status_check")
    op.execute("ALTER TABLE contact_leads DROP COLUMN IF EXISTS follow_up_at")
    op.execute("ALTER TABLE contact_leads DROP COLUMN IF EXISTS internal_notes")
    op.execute("DROP INDEX IF EXISTS subscriptions_one_live_per_tenant")
    op.execute("ALTER TABLE plan_versions DROP CONSTRAINT IF EXISTS plan_versions_status_check")
    op.execute("ALTER TABLE plan_versions DROP COLUMN IF EXISTS created_by")
    op.execute("ALTER TABLE plan_versions DROP COLUMN IF EXISTS retired_at")
    op.execute("ALTER TABLE plan_versions DROP COLUMN IF EXISTS effective_at")
    op.execute("ALTER TABLE plan_versions DROP COLUMN IF EXISTS status")
    op.execute("UPDATE plan_versions SET published_at=now() WHERE published_at IS NULL")
    op.execute("ALTER TABLE plan_versions ALTER COLUMN published_at SET NOT NULL")
    op.execute("ALTER TABLE staff_users DROP COLUMN IF EXISTS disabled_at")
