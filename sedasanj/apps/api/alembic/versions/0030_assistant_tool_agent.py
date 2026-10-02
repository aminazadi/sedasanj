"""Add assistant tool executions and durable knowledge retry metadata.

Revision ID: 0030_assistant_tool_agent
Revises: 0029_durable_transcript_corrections
"""

from alembic import op

revision = "0030_assistant_tool_agent"
down_revision = "0029_durable_transcript_corrections"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE assistant_tool_runs (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenants(id),
            conversation_id uuid NOT NULL REFERENCES chat_conversations(id) ON DELETE CASCADE,
            user_message_id uuid NOT NULL REFERENCES chat_messages(id) ON DELETE CASCADE,
            assistant_message_id uuid REFERENCES chat_messages(id) ON DELETE SET NULL,
            tool_call_id varchar(100) NOT NULL,
            tool_name varchar(80) NOT NULL,
            status varchar(24) NOT NULL CHECK (status IN ('running','succeeded','failed')),
            arguments jsonb NOT NULL DEFAULT '{}',
            result_preview jsonb,
            error_code varchar(80),
            duration_ms integer,
            started_at timestamptz NOT NULL DEFAULT now(),
            completed_at timestamptz,
            CONSTRAINT assistant_tool_runs_call_key UNIQUE (conversation_id, tool_call_id)
        );
        CREATE INDEX idx_assistant_tool_runs_message
          ON assistant_tool_runs(user_message_id, started_at);
        ALTER TABLE assistant_tool_runs ENABLE ROW LEVEL SECURITY;
        ALTER TABLE assistant_tool_runs FORCE ROW LEVEL SECURITY;
        CREATE POLICY assistant_tool_runs_tenant_isolation ON assistant_tool_runs
          USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
            OR current_setting('app.staff', true) = 'on')
          WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
            OR current_setting('app.staff', true) = 'on');
        GRANT SELECT, INSERT, UPDATE, DELETE ON assistant_tool_runs TO cbi_app;

        ALTER TABLE call_knowledge ADD COLUMN attempt_count integer NOT NULL DEFAULT 0;
        ALTER TABLE call_knowledge ADD COLUMN last_attempt_at timestamptz;
        ALTER TABLE call_knowledge ADD COLUMN next_retry_at timestamptz;
        CREATE INDEX idx_call_knowledge_retry
          ON call_knowledge(vector_status, next_retry_at);

        ALTER TABLE transcript_chunks ADD COLUMN source_revision_id uuid
          REFERENCES transcript_revisions(id) ON DELETE SET NULL;
        ALTER TABLE transcript_chunks ADD COLUMN embedding_model text;
        ALTER TABLE transcript_chunks ADD COLUMN vector_status varchar(24) NOT NULL DEFAULT 'pending';
        ALTER TABLE transcript_chunks ADD COLUMN attempt_count integer NOT NULL DEFAULT 0;
        ALTER TABLE transcript_chunks ADD COLUMN last_attempt_at timestamptz;
        ALTER TABLE transcript_chunks ADD COLUMN next_retry_at timestamptz;
        ALTER TABLE transcript_chunks ADD COLUMN error_detail text;
        ALTER TABLE transcript_chunks ADD CONSTRAINT transcript_chunks_vector_status_check
          CHECK (vector_status IN ('pending','ready','failed'));
        CREATE INDEX idx_transcript_chunks_retry
          ON transcript_chunks(tenant_id, vector_status, next_retry_at);
    """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE IF EXISTS assistant_tool_runs;
        DROP INDEX IF EXISTS idx_call_knowledge_retry;
        ALTER TABLE call_knowledge DROP COLUMN IF EXISTS next_retry_at;
        ALTER TABLE call_knowledge DROP COLUMN IF EXISTS last_attempt_at;
        ALTER TABLE call_knowledge DROP COLUMN IF EXISTS attempt_count;
        DROP INDEX IF EXISTS idx_transcript_chunks_retry;
        ALTER TABLE transcript_chunks DROP CONSTRAINT IF EXISTS transcript_chunks_vector_status_check;
        ALTER TABLE transcript_chunks DROP COLUMN IF EXISTS error_detail;
        ALTER TABLE transcript_chunks DROP COLUMN IF EXISTS next_retry_at;
        ALTER TABLE transcript_chunks DROP COLUMN IF EXISTS last_attempt_at;
        ALTER TABLE transcript_chunks DROP COLUMN IF EXISTS attempt_count;
        ALTER TABLE transcript_chunks DROP COLUMN IF EXISTS vector_status;
        ALTER TABLE transcript_chunks DROP COLUMN IF EXISTS embedding_model;
        ALTER TABLE transcript_chunks DROP COLUMN IF EXISTS source_revision_id;
    """)
