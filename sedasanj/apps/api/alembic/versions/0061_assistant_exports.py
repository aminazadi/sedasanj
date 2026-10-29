"""Add tenant-scoped expiring assistant file exports."""

from alembic import op

revision = "0061_assistant_exports"
down_revision = "0060_pbx_extensions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE TABLE assistant_exports (
        id UUID PRIMARY KEY,
        tenant_id UUID NOT NULL REFERENCES tenants(id),
        user_id UUID REFERENCES users(id) ON DELETE SET NULL,
        conversation_id UUID REFERENCES chat_conversations(id) ON DELETE SET NULL,
        dataset TEXT NOT NULL,
        format TEXT NOT NULL,
        filename TEXT NOT NULL,
        storage_key TEXT NOT NULL UNIQUE,
        size_bytes BIGINT NOT NULL,
        row_count INTEGER NOT NULL,
        filters JSONB NOT NULL DEFAULT '{}',
        expires_at TIMESTAMPTZ NOT NULL,
        deleted_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )""")
    op.execute(
        "CREATE INDEX idx_assistant_exports_expiry ON assistant_exports (expires_at) "
        "WHERE deleted_at IS NULL"
    )
    op.execute("ALTER TABLE assistant_exports ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE assistant_exports FORCE ROW LEVEL SECURITY")
    op.execute("""CREATE POLICY assistant_exports_tenant_isolation ON assistant_exports
        USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               OR current_setting('app.staff', true) = 'on')
        WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               OR current_setting('app.staff', true) = 'on')""")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON assistant_exports TO cbi_app")


def downgrade() -> None:
    op.drop_table("assistant_exports")
