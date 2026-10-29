"""Add the tenant phonebook (contacts) used to label callers in call lists and details."""

from alembic import op

revision = "0057_contacts"
down_revision = "0056_module_release_compat"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE TABLE contacts (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    tenant_id UUID NOT NULL,
    phone_number VARCHAR(15) NOT NULL,
    name VARCHAR(200) NOT NULL,
    company VARCHAR(200),
    email VARCHAR(254),
    notes TEXT,
    created_by UUID,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT contacts_tenant_phone_key UNIQUE (tenant_id, phone_number),
    CONSTRAINT contacts_phone_check CHECK (phone_number ~ '^[0-9]{3,15}$'),
    FOREIGN KEY(tenant_id) REFERENCES tenants (id),
    FOREIGN KEY(created_by) REFERENCES users (id) ON DELETE SET NULL
)""")
    op.execute("CREATE INDEX idx_contacts_tenant_name ON contacts (tenant_id, name)")
    op.execute("ALTER TABLE contacts ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE contacts FORCE ROW LEVEL SECURITY")
    op.execute("""CREATE POLICY contacts_tenant_isolation ON contacts
        USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               OR current_setting('app.staff', true) = 'on')
        WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               OR current_setting('app.staff', true) = 'on')""")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON contacts TO cbi_app")


def downgrade() -> None:
    op.drop_table("contacts")
