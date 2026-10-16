"""Add organization scheduled assistant reports and immutable execution archives."""

from alembic import op

revision = "0050_scheduled_reports"
down_revision = "0049_quick_demo_qr_login"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE TABLE scheduled_reports (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    tenant_id UUID NOT NULL,
    created_by UUID,
    name VARCHAR(200) NOT NULL,
    instructions TEXT NOT NULL,
    enabled BOOLEAN NOT NULL,
    schedule_mode VARCHAR(16) NOT NULL,
    interval_hours INTEGER,
    fixed_hours INTEGER[] NOT NULL,
    window_start TIMESTAMP WITH TIME ZONE NOT NULL,
    next_run_at TIMESTAMP WITH TIME ZONE,
    archived_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT scheduled_reports_mode_check CHECK (schedule_mode IN ('interval','fixed')),
    CONSTRAINT scheduled_reports_schedule_check CHECK (
        (schedule_mode = 'interval' AND interval_hours IS NOT NULL
         AND interval_hours BETWEEN 1 AND 8760 AND cardinality(fixed_hours) = 0)
        OR (schedule_mode = 'fixed' AND interval_hours IS NULL
            AND cardinality(fixed_hours) BETWEEN 1 AND 24
            AND 0 <= ALL(fixed_hours) AND 23 >= ALL(fixed_hours))),
    FOREIGN KEY(tenant_id) REFERENCES tenants (id),
    FOREIGN KEY(created_by) REFERENCES users (id) ON DELETE SET NULL
)""")
    op.execute(
        "CREATE INDEX idx_scheduled_reports_due ON scheduled_reports (tenant_id, next_run_at)"
    )
    op.execute("""CREATE TABLE scheduled_report_runs (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    tenant_id UUID NOT NULL,
    report_id UUID NOT NULL,
    requested_by UUID,
    usage_id UUID,
    trigger VARCHAR(16) NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL,
    name VARCHAR(200) NOT NULL,
    instructions TEXT NOT NULL,
    from_date TIMESTAMP WITH TIME ZONE NOT NULL,
    to_date TIMESTAMP WITH TIME ZONE NOT NULL,
    timezone TEXT NOT NULL,
    status VARCHAR(16) NOT NULL,
    memory_snapshot JSONB NOT NULL,
    content TEXT,
    sources JSONB NOT NULL,
    coverage JSONB NOT NULL,
    model TEXT,
    error_code VARCHAR(80),
    error_detail TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    PRIMARY KEY (id),
    CONSTRAINT scheduled_report_runs_idempotency_key UNIQUE (tenant_id, report_id, idempotency_key),
    CONSTRAINT scheduled_report_runs_status_check
        CHECK (status IN ('queued','running','succeeded','failed')),
    CONSTRAINT scheduled_report_runs_trigger_check CHECK (trigger IN ('scheduled','manual')),
    CONSTRAINT scheduled_report_runs_window_check CHECK (from_date < to_date),
    FOREIGN KEY(tenant_id) REFERENCES tenants (id),
    FOREIGN KEY(report_id) REFERENCES scheduled_reports (id),
    FOREIGN KEY(requested_by) REFERENCES users (id) ON DELETE SET NULL,
    FOREIGN KEY(usage_id) REFERENCES assistant_usage (id) ON DELETE SET NULL
)""")
    op.execute(
        "CREATE UNIQUE INDEX idx_scheduled_report_runs_active "
        "ON scheduled_report_runs (report_id) WHERE status IN ('queued','running')"
    )
    op.execute(
        "CREATE INDEX idx_scheduled_report_runs_archive "
        "ON scheduled_report_runs (tenant_id, created_at)"
    )
    for table in ("scheduled_reports", "scheduled_report_runs"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""CREATE POLICY {table}_tenant_isolation ON {table}
            USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
                   OR current_setting('app.staff', true) = 'on')
            WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
                   OR current_setting('app.staff', true) = 'on')""")
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO cbi_app")


def downgrade() -> None:
    op.drop_table("scheduled_report_runs")
    op.drop_table("scheduled_reports")
