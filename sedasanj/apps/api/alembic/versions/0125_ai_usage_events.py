"""Durable ledger of exact token usage reported by AI providers (aiservice, 9Router)."""

from alembic import op

revision = "0125_ai_usage_events"
down_revision = "0124_local_model_assistant_help"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE TABLE ai_usage_events (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id uuid NOT NULL REFERENCES tenants(id),
        feature text NOT NULL,
        provider text NOT NULL,
        origin text,
        model text,
        prompt_tokens bigint CHECK (prompt_tokens >= 0),
        completion_tokens bigint CHECK (completion_tokens >= 0),
        total_tokens bigint CHECK (total_tokens >= 0),
        usage_source text NOT NULL CHECK (usage_source IN ('reported', 'unavailable')),
        audio_seconds numeric(12, 3) CHECK (audio_seconds >= 0),
        provider_task_id text,
        call_id uuid,
        dedupe_key text UNIQUE,
        created_at timestamptz NOT NULL DEFAULT now()
    )""")
    op.execute(
        "CREATE INDEX idx_ai_usage_events_tenant_time "
        "ON ai_usage_events (tenant_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX idx_ai_usage_events_feature "
        "ON ai_usage_events (tenant_id, feature, model, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX idx_ai_usage_events_call ON ai_usage_events (tenant_id, call_id) "
        "WHERE call_id IS NOT NULL"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ai_usage_events TO cbi_app")
    op.execute("ALTER TABLE ai_usage_events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE ai_usage_events FORCE ROW LEVEL SECURITY")
    op.execute("""CREATE POLICY ai_usage_events_tenant_isolation ON ai_usage_events
        USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
            OR current_setting('app.staff', true) = 'on')
        WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
            OR current_setting('app.staff', true) = 'on')""")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ai_usage_events")
