"""Add immutable ASR transcript revisions.

Revision ID: 0040_asr_transcript_revisions
Revises: 0039_operator_score_needs_review
"""

from alembic import op

revision = "0040_asr_transcript_revisions"
down_revision = "0039_operator_score_needs_review"
branch_labels = None
depends_on = None


def upgrade() -> None:
    statements = [
        """
        CREATE TABLE asr_transcript_revisions (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          call_id uuid NOT NULL REFERENCES calls(id) ON DELETE CASCADE,
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          status text NOT NULL,
          trigger text NOT NULL,
          full_text text,
          asr_model text,
          asr_version text,
          speaker_mode text,
          timestamp_source text,
          metrics jsonb,
          error_code text,
          error_detail text,
          created_at timestamptz NOT NULL DEFAULT now(),
          completed_at timestamptz,
          activated_at timestamptz,
          CONSTRAINT asr_transcript_revisions_status_check
            CHECK (status IN ('queued','running','succeeded','failed')),
          CONSTRAINT asr_transcript_revisions_trigger_check
            CHECK (trigger IN ('initial','manual'))
        )
        """,
        """
        CREATE INDEX idx_asr_transcript_revisions_call
          ON asr_transcript_revisions (call_id, created_at DESC)
        """,
        """
        CREATE TABLE asr_transcript_revision_segments (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          revision_id uuid NOT NULL REFERENCES asr_transcript_revisions(id) ON DELETE CASCADE,
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          position integer NOT NULL,
          channel smallint NOT NULL,
          t_start_ms integer NOT NULL,
          t_end_ms integer NOT NULL,
          text text NOT NULL,
          confidence real,
          metadata jsonb,
          CONSTRAINT asr_revision_segments_channel_check CHECK (channel IN (0,1)),
          CONSTRAINT asr_revision_segments_revision_position_key UNIQUE (revision_id, position)
        )
        """,
        """
        CREATE INDEX idx_asr_revision_segments_revision
          ON asr_transcript_revision_segments (revision_id, position)
        """,
        "ALTER TABLE transcripts ADD COLUMN active_asr_revision_id uuid",
        "ALTER TABLE transcript_revisions ADD COLUMN asr_revision_id uuid",
        """
        INSERT INTO asr_transcript_revisions
          (id, call_id, tenant_id, status, trigger, full_text, asr_model, asr_version,
           speaker_mode, timestamp_source, completed_at, activated_at, created_at)
        SELECT gen_random_uuid(), t.call_id, t.tenant_id, 'succeeded', 'initial', t.full_text,
               t.asr_model, t.asr_version,
               CASE WHEN a.channels = 1 THEN 'mono_unknown' ELSE 'dual_channel' END,
               CASE WHEN count(u.id) > 1 THEN 'legacy_segments' ELSE 'legacy_coarse' END,
               t.created_at, t.created_at, t.created_at
        FROM transcripts t
        LEFT JOIN calls c ON c.id = t.call_id
        LEFT JOIN audio_objects a ON a.id = c.audio_id
        LEFT JOIN utterances u ON u.call_id = t.call_id AND u.tenant_id = t.tenant_id
        GROUP BY t.call_id, t.tenant_id, t.full_text, t.asr_model, t.asr_version,
                 t.created_at, a.channels
        """,
        """
        UPDATE transcripts t
        SET active_asr_revision_id = r.id
        FROM asr_transcript_revisions r
        WHERE r.call_id = t.call_id AND r.tenant_id = t.tenant_id
        """,
        """
        INSERT INTO asr_transcript_revision_segments
          (revision_id, tenant_id, position, channel, t_start_ms, t_end_ms, text, confidence, metadata)
        SELECT r.id, u.tenant_id,
               row_number() OVER (PARTITION BY u.call_id ORDER BY u.t_start_ms, u.channel, u.id) - 1,
               u.channel, u.t_start_ms, u.t_end_ms, u.text, u.confidence, u.metadata
        FROM utterances u
        JOIN asr_transcript_revisions r
          ON r.call_id = u.call_id AND r.tenant_id = u.tenant_id
        """,
        """
        UPDATE transcript_revisions tr
        SET asr_revision_id = t.active_asr_revision_id
        FROM transcripts t
        WHERE t.call_id = tr.call_id AND t.tenant_id = tr.tenant_id
        """,
        """
        ALTER TABLE transcripts
          ADD CONSTRAINT transcripts_active_asr_revision_id_fkey
          FOREIGN KEY (active_asr_revision_id) REFERENCES asr_transcript_revisions(id) ON DELETE SET NULL
        """,
        """
        ALTER TABLE transcript_revisions
          ADD CONSTRAINT transcript_revisions_asr_revision_id_fkey
          FOREIGN KEY (asr_revision_id) REFERENCES asr_transcript_revisions(id) ON DELETE SET NULL
        """,
        """
        GRANT SELECT, INSERT, UPDATE, DELETE ON
          asr_transcript_revisions, asr_transcript_revision_segments TO cbi_app
        """,
        "ALTER TABLE asr_transcript_revisions ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE asr_transcript_revisions FORCE ROW LEVEL SECURITY",
        """
        CREATE POLICY asr_transcript_revisions_tenant_isolation ON asr_transcript_revisions
          USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
                 OR current_setting('app.staff', true) = 'on')
          WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
                      OR current_setting('app.staff', true) = 'on')
        """,
        "ALTER TABLE asr_transcript_revision_segments ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE asr_transcript_revision_segments FORCE ROW LEVEL SECURITY",
        """
        CREATE POLICY asr_transcript_revision_segments_tenant_isolation
          ON asr_transcript_revision_segments
          USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
                 OR current_setting('app.staff', true) = 'on')
          WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
                      OR current_setting('app.staff', true) = 'on')
        """,
    ]
    for statement in statements:
        op.execute(statement)


def downgrade() -> None:
    statements = [
        "ALTER TABLE transcript_revisions DROP CONSTRAINT IF EXISTS transcript_revisions_asr_revision_id_fkey",
        "ALTER TABLE transcripts DROP CONSTRAINT IF EXISTS transcripts_active_asr_revision_id_fkey",
        "ALTER TABLE transcript_revisions DROP COLUMN IF EXISTS asr_revision_id",
        "ALTER TABLE transcripts DROP COLUMN IF EXISTS active_asr_revision_id",
        "DROP TABLE IF EXISTS asr_transcript_revision_segments",
        "DROP TABLE IF EXISTS asr_transcript_revisions",
    ]
    for statement in statements:
        op.execute(statement)
