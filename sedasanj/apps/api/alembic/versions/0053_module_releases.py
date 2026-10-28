"""Add signed FreePBX module releases, installation heartbeats and update history."""

from alembic import op

revision = "0053_module_releases"
down_revision = "0052_scheduled_report_retries"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE TABLE module_releases (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    product VARCHAR(64) NOT NULL,
    version VARCHAR(32) NOT NULL,
    version_major INTEGER NOT NULL,
    version_minor INTEGER NOT NULL,
    version_patch INTEGER NOT NULL,
    title VARCHAR(200) NOT NULL,
    changelog_html TEXT NOT NULL,
    changelog_plain TEXT NOT NULL,
    severity VARCHAR(16) NOT NULL,
    channel VARCHAR(16) NOT NULL,
    min_freepbx_major INTEGER,
    min_from_version VARCHAR(32),
    artifact_key TEXT NOT NULL,
    artifact_sha256 CHAR(64) NOT NULL,
    artifact_size BIGINT NOT NULL,
    signature_b64 TEXT NOT NULL,
    status VARCHAR(16) NOT NULL,
    published_at TIMESTAMP WITH TIME ZONE,
    created_by UUID,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT module_releases_product_version_key UNIQUE (product, version),
    CONSTRAINT module_releases_severity_check
        CHECK (severity IN ('normal','recommended','critical','security')),
    CONSTRAINT module_releases_channel_check CHECK (channel IN ('stable','beta')),
    CONSTRAINT module_releases_status_check CHECK (status IN ('draft','published','revoked')),
    FOREIGN KEY(created_by) REFERENCES staff_users (id) ON DELETE SET NULL
)""")
    op.execute(
        "CREATE INDEX idx_module_releases_latest ON module_releases "
        "(product, status, version_major DESC, version_minor DESC, version_patch DESC)"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON module_releases TO cbi_app")

    op.execute("""CREATE TABLE module_installations (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    tenant_id UUID NOT NULL,
    api_key_id UUID,
    product VARCHAR(64) NOT NULL,
    host_uuid VARCHAR(64) NOT NULL,
    hostname VARCHAR(255),
    freepbx_version VARCHAR(64),
    php_version VARCHAR(32),
    module_version VARCHAR(32) NOT NULL,
    service_status VARCHAR(32),
    last_seen_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    last_update_status VARCHAR(16),
    last_update_error TEXT,
    last_update_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT module_installations_host_key UNIQUE (tenant_id, product, host_uuid),
    FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE,
    FOREIGN KEY(api_key_id) REFERENCES api_keys (id) ON DELETE SET NULL
)""")
    op.execute(
        "CREATE INDEX idx_module_installations_version "
        "ON module_installations (product, module_version)"
    )

    op.execute("""CREATE TABLE module_update_events (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    tenant_id UUID NOT NULL,
    installation_id UUID NOT NULL,
    release_id UUID,
    from_version VARCHAR(32),
    to_version VARCHAR(32) NOT NULL,
    status VARCHAR(16) NOT NULL,
    message TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT module_update_events_status_check
        CHECK (status IN ('started','succeeded','failed','rolled_back')),
    FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE,
    FOREIGN KEY(installation_id) REFERENCES module_installations (id) ON DELETE CASCADE,
    FOREIGN KEY(release_id) REFERENCES module_releases (id) ON DELETE SET NULL
)""")
    op.execute(
        "CREATE INDEX idx_module_update_events_installation "
        "ON module_update_events (installation_id, created_at DESC)"
    )
    for table in ("module_installations", "module_update_events"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""CREATE POLICY {table}_tenant_isolation ON {table}
            USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
                   OR current_setting('app.staff', true) = 'on')
            WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
                   OR current_setting('app.staff', true) = 'on')""")
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO cbi_app")


def downgrade() -> None:
    op.drop_table("module_update_events")
    op.drop_table("module_installations")
    op.drop_table("module_releases")
