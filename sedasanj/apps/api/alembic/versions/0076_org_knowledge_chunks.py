"""Vector-searchable chunks for organization data beyond calls.

Revision ID: 0076_org_knowledge_chunks
Revises: 0075_coach_rubric_help
"""

from __future__ import annotations

from alembic import op

revision = "0076_org_knowledge_chunks"
down_revision = "0075_coach_rubric_help"
branch_labels = None
depends_on = None

_TENANT_CHECK = (
    "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid "
    "OR current_setting('app.staff', true) = 'on'"
)


def upgrade() -> None:
    op.execute(
        "CREATE TABLE org_knowledge_chunks ("
        "id uuid PRIMARY KEY DEFAULT gen_random_uuid(), "
        "tenant_id uuid NOT NULL REFERENCES tenants(id), "
        "source_type text NOT NULL, "
        "source_id uuid NOT NULL, "
        "ordinal integer NOT NULL, "
        "call_id uuid REFERENCES calls(id) ON DELETE CASCADE, "
        "access text NOT NULL DEFAULT 'tenant' "
        "CHECK (access IN ('tenant','call','admin')), "
        "title text NOT NULL DEFAULT '', "
        "content text NOT NULL, "
        "content_sha256 text NOT NULL, "
        "source_updated_at timestamptz NOT NULL, "
        "embedding vector, "
        "embedding_model text, "
        "embedding_provider text NOT NULL DEFAULT 'aiservice', "
        "vector_status varchar(24) NOT NULL DEFAULT 'pending' "
        "CHECK (vector_status IN ('pending','ready','failed')), "
        "attempt_count integer NOT NULL DEFAULT 0, "
        "last_attempt_at timestamptz, "
        "next_retry_at timestamptz, "
        "error_detail text, "
        "created_at timestamptz NOT NULL DEFAULT now(), "
        "UNIQUE (source_type, source_id, ordinal))"
    )
    op.execute(
        "CREATE INDEX idx_org_knowledge_chunks_tenant_source "
        "ON org_knowledge_chunks (tenant_id, source_type, vector_status)"
    )
    op.execute("CREATE INDEX idx_org_knowledge_chunks_call ON org_knowledge_chunks (call_id)")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON org_knowledge_chunks TO cbi_app")
    op.execute("ALTER TABLE org_knowledge_chunks ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE org_knowledge_chunks FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY org_knowledge_chunks_tenant_isolation ON org_knowledge_chunks "
        f"USING ({_TENANT_CHECK}) WITH CHECK ({_TENANT_CHECK})"
    )
    # Installations that already saved an enabled-tools list would never expose the new tool.
    op.execute(
        "DO $$ BEGIN IF to_regclass('platform_settings') IS NOT NULL THEN "
        "UPDATE platform_settings "
        "SET value = (value::jsonb || '[\"search_knowledge\"]'::jsonb)::text "
        "WHERE key = 'assistant_enabled_tools' AND NOT (value::jsonb ? 'search_knowledge'); "
        "END IF; END $$"
    )


def downgrade() -> None:
    op.execute(
        "DO $$ BEGIN IF to_regclass('platform_settings') IS NOT NULL THEN "
        "UPDATE platform_settings SET value = (value::jsonb - 'search_knowledge')::text "
        "WHERE key = 'assistant_enabled_tools'; END IF; END $$"
    )
    op.execute(
        "DROP POLICY IF EXISTS org_knowledge_chunks_tenant_isolation ON org_knowledge_chunks"
    )
    op.execute("DROP TABLE IF EXISTS org_knowledge_chunks")
