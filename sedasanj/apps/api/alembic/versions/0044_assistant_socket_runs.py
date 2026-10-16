"""Persist assistant socket runs and resumable events.

Revision ID: 0044_assistant_socket_runs
Revises: 0043_organization_memory
"""

from alembic import op

revision = "0044_assistant_socket_runs"
down_revision = "0043_organization_memory"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE assistant_runs (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenants(id),
            owner_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            conversation_id uuid NOT NULL REFERENCES chat_conversations(id) ON DELETE CASCADE,
            user_message_id uuid NOT NULL REFERENCES chat_messages(id) ON DELETE CASCADE,
            assistant_message_id uuid REFERENCES chat_messages(id) ON DELETE SET NULL,
            idempotency_key varchar(128) NOT NULL,
            status varchar(24) NOT NULL DEFAULT 'queued'
                CHECK (status IN ('queued','running','succeeded','failed','cancelled')),
            next_sequence bigint NOT NULL DEFAULT 1,
            last_event_sequence bigint NOT NULL DEFAULT 0,
            last_event_type varchar(64),
            last_event_payload jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT assistant_runs_idempotency_key UNIQUE (tenant_id, owner_id, idempotency_key)
        )
    """)
    op.execute(
        "CREATE INDEX idx_assistant_runs_conversation_status "
        "ON assistant_runs(conversation_id, status)"
    )
    op.execute("""
        CREATE TABLE assistant_run_events (
            run_id uuid NOT NULL REFERENCES assistant_runs(id) ON DELETE CASCADE,
            sequence bigint NOT NULL,
            event varchar(64) NOT NULL,
            payload jsonb NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY(run_id, sequence)
        )
    """)
    op.execute(
        "CREATE INDEX idx_assistant_run_events_created_at ON assistant_run_events(created_at)"
    )
    op.execute("ALTER TABLE assistant_runs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE assistant_runs FORCE ROW LEVEL SECURITY")
    op.execute("""CREATE POLICY assistant_runs_tenant_isolation ON assistant_runs
        USING (
            tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
            OR current_setting('app.staff', true) = 'on'
        )
        WITH CHECK (
            tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
            OR current_setting('app.staff', true) = 'on'
        )""")
    op.execute("ALTER TABLE assistant_run_events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE assistant_run_events FORCE ROW LEVEL SECURITY")
    op.execute("""CREATE POLICY assistant_run_events_tenant_isolation ON assistant_run_events
        USING (EXISTS (SELECT 1 FROM assistant_runs r WHERE r.id = run_id))
        WITH CHECK (EXISTS (SELECT 1 FROM assistant_runs r WHERE r.id = run_id))""")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON assistant_runs, assistant_run_events TO cbi_app"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS assistant_run_events")
    op.execute("DROP TABLE IF EXISTS assistant_runs")
