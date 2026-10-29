"""Add module diagnostics reports (doctor results sent by FreePBX hosts)."""

from alembic import op

revision = "0055_module_diagnostics"
down_revision = "0054_help_center"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE TABLE module_diagnostics (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    tenant_id UUID NOT NULL,
    installation_id UUID NOT NULL,
    module_version VARCHAR(32) NOT NULL,
    ok BOOLEAN NOT NULL,
    failed_checks INTEGER NOT NULL DEFAULT 0,
    report JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE,
    FOREIGN KEY(installation_id) REFERENCES module_installations (id) ON DELETE CASCADE
)""")
    op.execute(
        "CREATE INDEX idx_module_diagnostics_installation "
        "ON module_diagnostics (installation_id, created_at DESC)"
    )
    op.execute("ALTER TABLE module_installations ADD COLUMN last_error_code VARCHAR(40)")
    op.execute("ALTER TABLE module_installations ADD COLUMN asterisk_version VARCHAR(64)")
    op.execute("ALTER TABLE module_installations ADD COLUMN os_name VARCHAR(80)")
    op.execute("ALTER TABLE module_diagnostics ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE module_diagnostics FORCE ROW LEVEL SECURITY")
    op.execute("""CREATE POLICY module_diagnostics_tenant_isolation ON module_diagnostics
        USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               OR current_setting('app.staff', true) = 'on')
        WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               OR current_setting('app.staff', true) = 'on')""")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON module_diagnostics TO cbi_app")


def downgrade() -> None:
    op.execute("ALTER TABLE module_installations DROP COLUMN os_name")
    op.execute("ALTER TABLE module_installations DROP COLUMN asterisk_version")
    op.execute("ALTER TABLE module_installations DROP COLUMN last_error_code")
    op.drop_table("module_diagnostics")
