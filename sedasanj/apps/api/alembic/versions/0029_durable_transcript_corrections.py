"""Add durable transcript correction revisions.

Revision ID: 0029_durable_transcript_corrections
Revises: 0028_assistant_conversation_pins
"""

from __future__ import annotations

from sqlalchemy import text

from alembic import op

revision = "0029_durable_transcript_corrections"
down_revision = "0028_assistant_conversation_pins"
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
        ALTER TABLE calls DROP CONSTRAINT IF EXISTS calls_status_check;
        ALTER TABLE calls ADD CONSTRAINT calls_status_check CHECK (status IN (
          'received','reserved','stored','transcribing','transcribed','correcting',
          'emotion_queued','emotion_analyzing','analyzing','analyzed','billed',
          'notified','complete','failed_retryable','failed_terminal','canceled'
        ));

        ALTER TABLE jobs DROP CONSTRAINT IF EXISTS jobs_kind_check;
        ALTER TABLE jobs ADD CONSTRAINT jobs_kind_check
          CHECK (kind IN ('asr','emotion','correction','llm','notify'));

        ALTER TABLE utterances ADD COLUMN confidence real;
        ALTER TABLE utterances ADD COLUMN metadata jsonb;

        CREATE TABLE transcript_revisions (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          call_id uuid NOT NULL REFERENCES calls(id) ON DELETE CASCADE,
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          idempotency_key text NOT NULL UNIQUE,
          source_sha256 text NOT NULL,
          profile_version text NOT NULL,
          trigger text NOT NULL CHECK (trigger IN ('automatic','manual')),
          mode text NOT NULL CHECK (mode IN ('text_only','audio_only','two_stage')),
          status text NOT NULL CHECK (
            status IN ('queued','running','validating','succeeded','failed')
          ),
          audio_models text[] NOT NULL,
          text_models text[] NOT NULL,
          raw_text text NOT NULL,
          corrected_text text,
          provider_task_id text,
          provider_model text,
          uncertain_items jsonb,
          metrics jsonb,
          error_code text,
          error_detail text,
          queued_at timestamptz NOT NULL DEFAULT now(),
          started_at timestamptz,
          provider_submitted_at timestamptz,
          completed_at timestamptz,
          activated_at timestamptz,
          created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX idx_transcript_revisions_call
          ON transcript_revisions (call_id, created_at DESC);
        CREATE INDEX idx_transcript_revisions_pending
          ON transcript_revisions (status, queued_at);

        CREATE TABLE transcript_revision_segments (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          revision_id uuid NOT NULL REFERENCES transcript_revisions(id) ON DELETE CASCADE,
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          source_utterance_id uuid REFERENCES utterances(id) ON DELETE SET NULL,
          position integer NOT NULL,
          channel smallint NOT NULL CHECK (channel IN (0,1)),
          t_start_ms integer NOT NULL,
          t_end_ms integer NOT NULL,
          source_text text NOT NULL,
          corrected_text text NOT NULL,
          confidence real,
          uncertain boolean NOT NULL DEFAULT false,
          metadata jsonb,
          CONSTRAINT transcript_revision_segments_revision_position_key
            UNIQUE (revision_id, position)
        );
        CREATE INDEX idx_transcript_revision_segments_revision
          ON transcript_revision_segments (revision_id, position);

        ALTER TABLE transcripts ADD COLUMN active_revision_id uuid;
        ALTER TABLE transcripts ADD CONSTRAINT transcripts_active_revision_fk
          FOREIGN KEY (active_revision_id) REFERENCES transcript_revisions(id) ON DELETE SET NULL;

        GRANT SELECT, INSERT, UPDATE, DELETE
          ON transcript_revisions, transcript_revision_segments TO cbi_app;

        ALTER TABLE transcript_revisions ENABLE ROW LEVEL SECURITY;
        ALTER TABLE transcript_revisions FORCE ROW LEVEL SECURITY;
        CREATE POLICY transcript_revisions_tenant_isolation ON transcript_revisions
          USING (
            tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
            OR current_setting('app.staff', true) = 'on'
          )
          WITH CHECK (
            tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
            OR current_setting('app.staff', true) = 'on'
          );

        ALTER TABLE transcript_revision_segments ENABLE ROW LEVEL SECURITY;
        ALTER TABLE transcript_revision_segments FORCE ROW LEVEL SECURITY;
        CREATE POLICY transcript_revision_segments_tenant_isolation
          ON transcript_revision_segments
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
        ALTER TABLE transcripts DROP CONSTRAINT IF EXISTS transcripts_active_revision_fk;
        ALTER TABLE transcripts DROP COLUMN IF EXISTS active_revision_id;
        DROP TABLE IF EXISTS transcript_revision_segments;
        DROP TABLE IF EXISTS transcript_revisions;
        ALTER TABLE utterances DROP COLUMN IF EXISTS metadata;
        ALTER TABLE utterances DROP COLUMN IF EXISTS confidence;

        ALTER TABLE jobs DROP CONSTRAINT IF EXISTS jobs_kind_check;
        ALTER TABLE jobs ADD CONSTRAINT jobs_kind_check
          CHECK (kind IN ('asr','emotion','llm','notify'));

        UPDATE calls SET status='transcribed' WHERE status='correcting';
        ALTER TABLE calls DROP CONSTRAINT IF EXISTS calls_status_check;
        ALTER TABLE calls ADD CONSTRAINT calls_status_check CHECK (status IN (
          'received','reserved','stored','transcribing','transcribed',
          'emotion_queued','emotion_analyzing','analyzing','analyzed','billed',
          'notified','complete','failed_retryable','failed_terminal','canceled'
        ));
        """
    )
