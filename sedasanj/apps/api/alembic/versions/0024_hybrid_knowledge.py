"""Add hybrid vector and graph indexing records.

Revision ID: 0024_hybrid_knowledge
Revises: 0023_projection_state
"""

from alembic import op

revision = "0024_hybrid_knowledge"
down_revision = "0023_projection_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE call_knowledge (
            call_id uuid PRIMARY KEY REFERENCES calls(id) ON DELETE CASCADE,
            tenant_id uuid NOT NULL REFERENCES tenants(id),
            operator_id uuid REFERENCES users(id) ON DELETE SET NULL,
            summary text NOT NULL,
            embedding vector,
            embedding_model text,
            vector_status varchar(24) NOT NULL DEFAULT 'pending',
            graph_status varchar(24) NOT NULL DEFAULT 'pending',
            indexed_at timestamptz,
            error_detail text,
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT call_knowledge_vector_status_check
              CHECK (vector_status IN ('pending','ready','failed')),
            CONSTRAINT call_knowledge_graph_status_check
              CHECK (graph_status IN ('pending','ready','failed'))
        )
    """)
    op.execute("""
        CREATE INDEX idx_call_knowledge_tenant_status
          ON call_knowledge(tenant_id, vector_status, graph_status)
    """)
    op.execute("ALTER TABLE call_knowledge ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE call_knowledge FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY call_knowledge_tenant_isolation ON call_knowledge
          USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
            OR current_setting('app.staff', true) = 'on')
          WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
            OR current_setting('app.staff', true) = 'on')
    """)
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON call_knowledge TO cbi_app")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS call_knowledge")
