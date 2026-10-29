"""Add PBX extensions synced from the FreePBX module, linkable to a contact and an operator."""

from alembic import op

revision = "0060_pbx_extensions"
down_revision = "0059_contact_geo"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE TABLE pbx_extensions (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    tenant_id UUID NOT NULL,
    extension VARCHAR(20) NOT NULL,
    pbx_name VARCHAR(200),
    active BOOLEAN DEFAULT true NOT NULL,
    contact_id UUID,
    user_id UUID,
    synced_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT pbx_extensions_tenant_extension_key UNIQUE (tenant_id, extension),
    CONSTRAINT pbx_extensions_extension_check CHECK (extension ~ '^[0-9*#]{1,20}$'),
    FOREIGN KEY(tenant_id) REFERENCES tenants (id),
    FOREIGN KEY(contact_id) REFERENCES contacts (id) ON DELETE SET NULL,
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE SET NULL
)""")
    op.execute(
        "CREATE UNIQUE INDEX pbx_extensions_tenant_user_key ON pbx_extensions (tenant_id, user_id) "
        "WHERE user_id IS NOT NULL"
    )
    op.execute("CREATE INDEX idx_pbx_extensions_contact ON pbx_extensions (contact_id)")
    op.execute("ALTER TABLE pbx_extensions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE pbx_extensions FORCE ROW LEVEL SECURITY")
    op.execute("""CREATE POLICY pbx_extensions_tenant_isolation ON pbx_extensions
        USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               OR current_setting('app.staff', true) = 'on')
        WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               OR current_setting('app.staff', true) = 'on')""")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON pbx_extensions TO cbi_app")


def downgrade() -> None:
    op.drop_table("pbx_extensions")
