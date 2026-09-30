"""Add durable dispatch and provider analysis steps.

Revision ID: 0008_durable_pipeline
Revises: 0007_processing_event_steps
"""

from __future__ import annotations

from sqlalchemy import text

from alembic import op

revision = "0008_durable_pipeline"
down_revision = "0007_processing_event_steps"
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
        ALTER TABLE jobs ADD COLUMN queued_at timestamptz NOT NULL DEFAULT now();
        ALTER TABLE jobs ADD COLUMN started_at timestamptz;
        ALTER TABLE jobs ADD COLUMN provider_submitted_at timestamptz;
        ALTER TABLE jobs ADD COLUMN completed_at timestamptz;

        CREATE TABLE job_outbox (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          job_id uuid REFERENCES jobs(id) ON DELETE CASCADE,
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          queue_name text NOT NULL,
          function_name text NOT NULL,
          payload jsonb NOT NULL,
          available_at timestamptz NOT NULL DEFAULT now(),
          dispatched_at timestamptz,
          attempts integer NOT NULL DEFAULT 0,
          last_error text,
          created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX idx_job_outbox_pending ON job_outbox (available_at)
          WHERE dispatched_at IS NULL;

        CREATE TABLE analysis_steps (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          analysis_run_id uuid NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          kind text NOT NULL CHECK (kind IN ('correction','map','reduce','extract','repair')),
          ordinal integer NOT NULL DEFAULT 0,
          status text NOT NULL CHECK (
            status IN ('queued','submitted','polling','succeeded','failed')
          ),
          system_prompt text NOT NULL,
          input_text text NOT NULL,
          input_sha256 text NOT NULL,
          idempotency_key text NOT NULL UNIQUE,
          provider_task_id text,
          result_text text,
          attempt integer NOT NULL DEFAULT 0,
          error_code text,
          error_detail text,
          queued_at timestamptz NOT NULL DEFAULT now(),
          submitted_at timestamptz,
          completed_at timestamptz,
          created_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT analysis_steps_run_kind_ordinal_key
            UNIQUE (analysis_run_id, kind, ordinal)
        );
        CREATE INDEX idx_analysis_steps_pending ON analysis_steps (status, queued_at);

        GRANT SELECT, INSERT, UPDATE, DELETE ON job_outbox, analysis_steps TO cbi_app;
        ALTER TABLE job_outbox ENABLE ROW LEVEL SECURITY;
        ALTER TABLE job_outbox FORCE ROW LEVEL SECURITY;
        CREATE POLICY job_outbox_tenant_isolation ON job_outbox
          USING (
            tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
            OR current_setting('app.staff', true) = 'on'
          )
          WITH CHECK (
            tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
            OR current_setting('app.staff', true) = 'on'
          );
        ALTER TABLE analysis_steps ENABLE ROW LEVEL SECURITY;
        ALTER TABLE analysis_steps FORCE ROW LEVEL SECURITY;
        CREATE POLICY analysis_steps_tenant_isolation ON analysis_steps
          USING (
            tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
            OR current_setting('app.staff', true) = 'on'
          )
          WITH CHECK (
            tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
            OR current_setting('app.staff', true) = 'on'
          );

        WITH inserted_jobs AS (
          INSERT INTO jobs (tenant_id, call_id, kind, status, attempt)
          SELECT c.tenant_id, c.id, 'llm', 'queued', 0
          FROM calls c
          WHERE c.status = 'transcribed'
            AND NOT EXISTS (
              SELECT 1 FROM jobs j
              WHERE j.call_id = c.id
                AND j.kind = 'llm'
                AND j.status IN ('queued', 'running')
            )
          RETURNING id, tenant_id, call_id
        )
        INSERT INTO job_outbox (
          job_id, tenant_id, queue_name, function_name, payload
        )
        SELECT
          id,
          tenant_id,
          'q:llm',
          'analyze_call',
          jsonb_build_object(
            'call_id', call_id::text,
            'analysis_run_id', NULL,
            'reanalysis', false,
            'previous_status', NULL,
            'recovery', true
          )
        FROM inserted_jobs;
        """
    )


def downgrade() -> None:
    _exec(
        """
        DROP TABLE IF EXISTS analysis_steps;
        DROP TABLE IF EXISTS job_outbox;
        ALTER TABLE jobs DROP COLUMN IF EXISTS completed_at;
        ALTER TABLE jobs DROP COLUMN IF EXISTS provider_submitted_at;
        ALTER TABLE jobs DROP COLUMN IF EXISTS started_at;
        ALTER TABLE jobs DROP COLUMN IF EXISTS queued_at;
        """
    )
