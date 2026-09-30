"""First-class follow-up tasks extracted from call analysis.

Revision ID: 0013_follow_up_tasks
Revises: 0012_operator_panel
"""

from __future__ import annotations

from sqlalchemy import text

from alembic import op

revision = "0013_follow_up_tasks"
down_revision = "0012_operator_panel"
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
        CREATE TABLE follow_up_tasks (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          call_id uuid NOT NULL REFERENCES calls(id) ON DELETE CASCADE,
          title text NOT NULL CHECK (btrim(title) <> ''),
          description text,
          status text NOT NULL DEFAULT 'open' CHECK (status IN ('open','done')),
          priority text CHECK (priority IS NULL OR priority IN ('low','normal','high')),
          due_date date,
          source_phone text,
          completed_at timestamptz,
          completed_by uuid REFERENCES users(id) ON DELETE SET NULL,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX idx_follow_up_tasks_call ON follow_up_tasks (call_id, created_at);
        CREATE INDEX idx_follow_up_tasks_tenant_status
          ON follow_up_tasks (tenant_id, status, due_date);
        GRANT SELECT, INSERT, UPDATE, DELETE ON follow_up_tasks TO cbi_app;
        ALTER TABLE follow_up_tasks ENABLE ROW LEVEL SECURITY;
        ALTER TABLE follow_up_tasks FORCE ROW LEVEL SECURITY;
        CREATE POLICY follow_up_tasks_tenant_isolation ON follow_up_tasks
          USING (
            tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
            OR current_setting('app.staff', true) = 'on'
          )
          WITH CHECK (
            tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
            OR current_setting('app.staff', true) = 'on'
          );
        INSERT INTO follow_up_tasks (
          tenant_id, call_id, title, status, source_phone, created_at, updated_at
        )
        SELECT DISTINCT ON (ci.call_id, lower(left(btrim(item), 500)))
          ci.tenant_id,
          ci.call_id,
          left(btrim(item), 500),
          'open',
          CASE
            WHEN c.direction = 'outbound' THEN COALESCE(c.dialed_number, c.caller_number)
            ELSE COALESCE(c.caller_number, c.dialed_number)
          END,
          COALESCE(
            (
              SELECT ar.created_at
              FROM analysis_runs ar
              WHERE ar.call_id = ci.call_id AND ar.status = 'succeeded'
              ORDER BY ar.created_at DESC
              LIMIT 1
            ),
            c.started_at,
            now()
          ),
          now()
        FROM call_insights ci
        JOIN calls c ON c.id = ci.call_id
        CROSS JOIN LATERAL jsonb_array_elements_text(
          CASE
            WHEN jsonb_typeof(ci.action_items) = 'array' THEN ci.action_items
            ELSE '[]'::jsonb
          END
        ) AS item
        WHERE btrim(item) <> ''
        ORDER BY ci.call_id, lower(left(btrim(item), 500)), item;
        """
    )


def downgrade() -> None:
    _exec(
        """
        DROP POLICY IF EXISTS follow_up_tasks_tenant_isolation ON follow_up_tasks;
        ALTER TABLE follow_up_tasks DISABLE ROW LEVEL SECURITY;
        DROP TABLE IF EXISTS follow_up_tasks;
        """
    )
