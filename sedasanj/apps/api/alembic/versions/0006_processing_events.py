"""Persist tenant-visible call processing events and failure details.

Revision ID: 0006_processing_events
Revises: 0005_sentiment_labels
"""

from __future__ import annotations

from sqlalchemy import text

from alembic import op

revision = "0006_processing_events"
down_revision = "0005_sentiment_labels"
branch_labels = None
depends_on = None


def _exec(sql: str) -> None:
    bind = op.get_bind()
    for part in sql.split(";"):
        statement = part.strip()
        if statement:
            bind.execute(text(statement))


def upgrade() -> None:
    _exec(
        """
        CREATE TABLE processing_events (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          call_id uuid NOT NULL REFERENCES calls(id) ON DELETE CASCADE,
          kind text NOT NULL CHECK (kind IN ('pipeline','asr','llm','notify')),
          level text NOT NULL DEFAULT 'info' CHECK (level IN ('info','success','warning','error')),
          status text,
          progress_pct smallint CHECK (
            progress_pct IS NULL OR (progress_pct >= 0 AND progress_pct <= 100)
          ),
          message text NOT NULL,
          error_code text,
          error_detail text,
          created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX idx_processing_events_call ON processing_events (call_id, created_at);
        GRANT SELECT, INSERT, UPDATE, DELETE ON processing_events TO cbi_app;
        ALTER TABLE processing_events ENABLE ROW LEVEL SECURITY;
        ALTER TABLE processing_events FORCE ROW LEVEL SECURITY;
        CREATE POLICY processing_events_tenant_isolation ON processing_events
          USING (
            tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
            OR current_setting('app.staff', true) = 'on'
          )
          WITH CHECK (
            tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
            OR current_setting('app.staff', true) = 'on'
          );
        """
    )


def downgrade() -> None:
    _exec(
        """
        DROP POLICY IF EXISTS processing_events_tenant_isolation ON processing_events;
        ALTER TABLE processing_events DISABLE ROW LEVEL SECURITY;
        DROP TABLE IF EXISTS processing_events;
        """
    )
