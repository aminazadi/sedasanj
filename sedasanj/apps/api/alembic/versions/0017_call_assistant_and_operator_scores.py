"""Add tenant call assistant and operator scoring records.

Revision ID: 0017_call_assistant_and_operator_scores
Revises: 0016_totp_self_service
"""

from sqlalchemy import text

from alembic import op

revision = "0017_call_assistant_and_operator_scores"
down_revision = "0016_totp_self_service"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    for statement in """
    ALTER TABLE tenants ADD COLUMN IF NOT EXISTS operator_ranking_visible boolean NOT NULL DEFAULT false;
    ALTER TABLE users ADD COLUMN IF NOT EXISTS display_name text;
    CREATE TABLE operator_score_rubrics (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL REFERENCES tenants(id), version integer NOT NULL, criteria jsonb NOT NULL, active boolean NOT NULL DEFAULT true, created_by uuid REFERENCES users(id) ON DELETE SET NULL, created_at timestamptz NOT NULL DEFAULT now(), UNIQUE (tenant_id, version));
    CREATE TABLE operator_call_scores (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL REFERENCES tenants(id), call_id uuid NOT NULL REFERENCES calls(id) ON DELETE CASCADE, analysis_run_id uuid REFERENCES analysis_runs(id) ON DELETE SET NULL, rubric_id uuid REFERENCES operator_score_rubrics(id) ON DELETE SET NULL, operator_id uuid REFERENCES users(id) ON DELETE SET NULL, operator_label text NOT NULL, model text NOT NULL, status text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','running','succeeded','failed','ineligible')), total_score real, criteria_scores jsonb, error_detail text, created_at timestamptz NOT NULL DEFAULT now(), completed_at timestamptz, UNIQUE (call_id, analysis_run_id));
    CREATE TABLE chat_conversations (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL REFERENCES tenants(id), owner_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE, call_id uuid REFERENCES calls(id) ON DELETE SET NULL, title text, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now());
    CREATE TABLE chat_messages (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), conversation_id uuid NOT NULL REFERENCES chat_conversations(id) ON DELETE CASCADE, tenant_id uuid NOT NULL REFERENCES tenants(id), role text NOT NULL CHECK (role IN ('user','assistant')), content text NOT NULL, status text NOT NULL DEFAULT 'succeeded' CHECK (status IN ('queued','running','succeeded','failed','insufficient_evidence')), model text, sources jsonb, created_at timestamptz NOT NULL DEFAULT now());
    CREATE TABLE transcript_chunks (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL REFERENCES tenants(id), call_id uuid NOT NULL REFERENCES calls(id) ON DELETE CASCADE, ordinal integer NOT NULL, content text NOT NULL, content_sha256 text NOT NULL, embedding vector(384), created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(call_id, ordinal));
    CREATE INDEX idx_operator_score_rubrics_active ON operator_score_rubrics (tenant_id, active);
    CREATE INDEX idx_operator_call_scores_tenant_operator ON operator_call_scores (tenant_id, operator_id, created_at DESC);
    CREATE INDEX idx_chat_conversations_owner ON chat_conversations (tenant_id, owner_id, updated_at DESC);
    CREATE INDEX idx_chat_messages_conversation ON chat_messages (conversation_id, created_at);
    CREATE INDEX idx_transcript_chunks_tenant_call ON transcript_chunks (tenant_id, call_id);
    GRANT SELECT, INSERT, UPDATE, DELETE ON operator_score_rubrics, operator_call_scores, chat_conversations, chat_messages, transcript_chunks TO cbi_app;
    ALTER TABLE operator_score_rubrics ENABLE ROW LEVEL SECURITY; ALTER TABLE operator_score_rubrics FORCE ROW LEVEL SECURITY;
    ALTER TABLE operator_call_scores ENABLE ROW LEVEL SECURITY; ALTER TABLE operator_call_scores FORCE ROW LEVEL SECURITY;
    ALTER TABLE chat_conversations ENABLE ROW LEVEL SECURITY; ALTER TABLE chat_conversations FORCE ROW LEVEL SECURITY;
    ALTER TABLE chat_messages ENABLE ROW LEVEL SECURITY; ALTER TABLE chat_messages FORCE ROW LEVEL SECURITY;
    ALTER TABLE transcript_chunks ENABLE ROW LEVEL SECURITY; ALTER TABLE transcript_chunks FORCE ROW LEVEL SECURITY;
    CREATE POLICY operator_score_rubrics_tenant_isolation ON operator_score_rubrics USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid OR current_setting('app.staff', true) = 'on') WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid OR current_setting('app.staff', true) = 'on');
    CREATE POLICY operator_call_scores_tenant_isolation ON operator_call_scores USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid OR current_setting('app.staff', true) = 'on') WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid OR current_setting('app.staff', true) = 'on');
    CREATE POLICY chat_conversations_tenant_isolation ON chat_conversations USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid OR current_setting('app.staff', true) = 'on') WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid OR current_setting('app.staff', true) = 'on');
    CREATE POLICY chat_messages_tenant_isolation ON chat_messages USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid OR current_setting('app.staff', true) = 'on') WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid OR current_setting('app.staff', true) = 'on');
    CREATE POLICY transcript_chunks_tenant_isolation ON transcript_chunks USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid OR current_setting('app.staff', true) = 'on') WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid OR current_setting('app.staff', true) = 'on');
    """.split(";"):
        if statement.strip():
            bind.execute(text(statement))


def downgrade() -> None:
    bind = op.get_bind()
    for statement in (
        "DROP TABLE IF EXISTS transcript_chunks",
        "DROP TABLE IF EXISTS chat_messages",
        "DROP TABLE IF EXISTS chat_conversations",
        "DROP TABLE IF EXISTS operator_call_scores",
        "DROP TABLE IF EXISTS operator_score_rubrics",
        "ALTER TABLE users DROP COLUMN IF EXISTS display_name",
        "ALTER TABLE tenants DROP COLUMN IF EXISTS operator_ranking_visible",
    ):
        bind.execute(text(statement))
