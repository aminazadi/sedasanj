"""SMS.ir event templates (admin managed) and a delivery log with idempotent sends.

Both tables are platform-wide (control database only): templates are a property of the platform's
SMS.ir account, and deliveries must be written before a tenant database is necessarily ready.
"""

from alembic import op

revision = "0133_sms_templates_deliveries"
down_revision = "0132_token_budget_help"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE TABLE sms_templates (
        event_key text PRIMARY KEY,
        template_id bigint CHECK (template_id > 0),
        parameters jsonb NOT NULL DEFAULT '{}'::jsonb,
        enabled boolean NOT NULL DEFAULT false,
        updated_at timestamptz NOT NULL DEFAULT now()
    )""")
    op.execute("""CREATE TABLE sms_deliveries (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        event_key text NOT NULL,
        tenant_id uuid,
        mobile text NOT NULL,
        params jsonb NOT NULL DEFAULT '{}'::jsonb,
        dedupe_key text NOT NULL UNIQUE,
        status text NOT NULL DEFAULT 'pending'
            CHECK (status IN ('pending', 'sent', 'failed', 'unknown', 'skipped')),
        attempts integer NOT NULL DEFAULT 0,
        last_error text,
        created_at timestamptz NOT NULL DEFAULT now(),
        sent_at timestamptz
    )""")
    op.execute(
        "CREATE INDEX idx_sms_deliveries_pending ON sms_deliveries (created_at) "
        "WHERE status = 'pending'"
    )
    op.execute(
        "CREATE INDEX idx_sms_deliveries_tenant ON sms_deliveries (tenant_id, created_at DESC)"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON sms_templates TO cbi_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON sms_deliveries TO cbi_app")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS sms_deliveries")
    op.execute("DROP TABLE IF EXISTS sms_templates")
