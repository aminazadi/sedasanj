"""Per-plan monthly LLM token budget and purchasable token top-ups.

NULL ``llm_monthly_tokens`` means unlimited, so existing plans and subscriptions behave exactly
as before until an admin sets a limit.
"""

from alembic import op

revision = "0131_plan_llm_token_budget"
down_revision = "0130_tenant_migration_error_code"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE plan_versions ADD COLUMN llm_monthly_tokens bigint "
        "CHECK (llm_monthly_tokens >= 0)"
    )
    op.execute(
        "ALTER TABLE subscriptions ADD COLUMN llm_monthly_tokens bigint "
        "CHECK (llm_monthly_tokens >= 0)"
    )
    op.execute("""CREATE TABLE token_grants (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id uuid NOT NULL REFERENCES tenants(id),
        source text NOT NULL CHECK (source IN ('purchase', 'admin_adjustment')),
        source_id uuid,
        total_tokens bigint NOT NULL CHECK (total_tokens > 0),
        remaining_tokens bigint NOT NULL CHECK (remaining_tokens >= 0),
        expires_at timestamptz,
        created_at timestamptz NOT NULL DEFAULT now(),
        CHECK (remaining_tokens <= total_tokens)
    )""")
    op.execute(
        "CREATE INDEX idx_token_grants_tenant_open ON token_grants (tenant_id, created_at) "
        "WHERE remaining_tokens > 0"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON token_grants TO cbi_app")
    op.execute("ALTER TABLE token_grants ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE token_grants FORCE ROW LEVEL SECURITY")
    op.execute("""CREATE POLICY token_grants_tenant_isolation ON token_grants
        USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
            OR current_setting('app.staff', true) = 'on')
        WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
            OR current_setting('app.staff', true) = 'on')""")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS token_grants")
    op.execute("ALTER TABLE subscriptions DROP COLUMN IF EXISTS llm_monthly_tokens")
    op.execute("ALTER TABLE plan_versions DROP COLUMN IF EXISTS llm_monthly_tokens")
