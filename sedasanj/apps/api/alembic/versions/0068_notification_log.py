"""Record subscription notices so each one is sent once per subscription period."""

from alembic import op

revision = "0068_notification_log"
down_revision = "0067_plan_flags_grant_check"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """CREATE TABLE notification_log (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    tenant_id uuid NOT NULL REFERENCES tenants(id),
    subscription_id uuid NOT NULL REFERENCES subscriptions(id),
    kind varchar(32) NOT NULL,
    period_key varchar(64) NOT NULL,
    channel varchar(16) NOT NULL DEFAULT 'email',
    status varchar(16) NOT NULL DEFAULT 'pending',
    attempts integer NOT NULL DEFAULT 0,
    last_error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    sent_at timestamptz,
    PRIMARY KEY (id),
    CONSTRAINT notification_log_status_check CHECK (status IN ('pending','sent','failed')),
    CONSTRAINT notification_log_once UNIQUE (subscription_id, kind, period_key, channel)
)"""
    )
    op.execute(
        "CREATE INDEX idx_notification_log_open ON notification_log (status, created_at) "
        "WHERE status <> 'sent'"
    )
    op.execute("ALTER TABLE notification_log ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE notification_log FORCE ROW LEVEL SECURITY")
    op.execute(
        """CREATE POLICY notification_log_tenant_isolation ON notification_log
    USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
        OR current_setting('app.staff', true) = 'on')
    WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
        OR current_setting('app.staff', true) = 'on')"""
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON notification_log TO cbi_app")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS notification_log")
