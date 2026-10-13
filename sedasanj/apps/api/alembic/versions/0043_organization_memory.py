"""Add tenant organization memory and assistant training mode.

Revision ID: 0043_organization_memory
Revises: 0042_chat_message_ordinal
"""

from alembic import op

revision = "0043_organization_memory"
down_revision = "0042_chat_message_ordinal"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE chat_conversations ADD COLUMN mode text NOT NULL DEFAULT 'normal'")
    op.execute("ALTER TABLE chat_conversations ADD CONSTRAINT chat_conversations_mode_check CHECK (mode IN ('normal','training'))")
    for table in ("analysis_runs", "transcript_revisions"):
        op.execute(f"ALTER TABLE {table} ADD COLUMN memory_snapshot jsonb")
        op.execute(f"ALTER TABLE {table} ADD COLUMN memory_context text")
        op.execute(f"ALTER TABLE {table} ADD COLUMN memory_sha256 varchar(64)")
    op.execute("""
        CREATE TABLE organization_memories (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            logical_key varchar(120) NOT NULL, version integer NOT NULL,
            supersedes_id uuid REFERENCES organization_memories(id) ON DELETE SET NULL,
            category varchar(40) NOT NULL, title varchar(200) NOT NULL, content text NOT NULL,
            structured_payload jsonb NOT NULL DEFAULT '{}'::jsonb, tags text[] NOT NULL DEFAULT '{}',
            applies_to text[] NOT NULL DEFAULT '{}', status varchar(24) NOT NULL DEFAULT 'draft',
            source_conversation_id uuid REFERENCES chat_conversations(id) ON DELETE SET NULL,
            source_message_id uuid REFERENCES chat_messages(id) ON DELETE SET NULL,
            created_by uuid REFERENCES users(id) ON DELETE SET NULL, approved_by uuid REFERENCES users(id) ON DELETE SET NULL,
            lock_version integer NOT NULL DEFAULT 1, idempotency_key varchar(120), created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(), approved_at timestamptz, archived_at timestamptz,
            CONSTRAINT organization_memories_category_check CHECK (category IN ('organization_profile','products_services','terminology','policies','analysis_rules','freeform')),
            CONSTRAINT organization_memories_status_check CHECK (status IN ('draft','active','rejected','superseded','archived')),
            CONSTRAINT organization_memories_version_check CHECK (version > 0),
            CONSTRAINT organization_memories_lock_version_check CHECK (lock_version > 0),
            CONSTRAINT organization_memories_version_key UNIQUE (tenant_id, logical_key, version),
            CONSTRAINT organization_memories_idempotency_key UNIQUE (tenant_id, idempotency_key),
            CONSTRAINT organization_memories_applies_to_check CHECK (applies_to <@ ARRAY['assistant','correction','analysis','scoring']::text[] AND cardinality(applies_to) > 0)
        )
    """)
    op.execute("CREATE UNIQUE INDEX uq_organization_memories_active ON organization_memories (tenant_id, logical_key) WHERE status = 'active'")
    op.execute("CREATE INDEX idx_organization_memories_tenant_status ON organization_memories (tenant_id, status, category)")
    op.execute("ALTER TABLE organization_memories ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE organization_memories FORCE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY organization_memories_tenant_isolation ON organization_memories USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid OR current_setting('app.staff', true) = 'on') WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid OR current_setting('app.staff', true) = 'on')")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON organization_memories TO cbi_app")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS organization_memories")
    for table in ("transcript_revisions", "analysis_runs"):
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS memory_sha256")
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS memory_context")
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS memory_snapshot")
    op.execute("ALTER TABLE chat_conversations DROP CONSTRAINT IF EXISTS chat_conversations_mode_check")
    op.execute("ALTER TABLE chat_conversations DROP COLUMN IF EXISTS mode")
