"""Meetings accept the on-device transcript instead of audio; per-organization AI instructions.

Adds the text-ingest columns on `meetings`, lets segments come from the device, records which
prompt and provider produced each minutes version and adds `tenant_ai_instructions`.
"""

from alembic import op

revision = "0095_meeting_text_ingest"
down_revision = "0094_meetings_help_content"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE meetings ADD COLUMN input_kind text NOT NULL DEFAULT 'audio'")
    op.execute(
        "ALTER TABLE meetings ADD CONSTRAINT meetings_input_kind_check "
        "CHECK (input_kind IN ('audio','text'))"
    )
    op.execute("ALTER TABLE meetings ADD COLUMN transcript_sha256 text")
    op.execute("ALTER TABLE meetings ADD COLUMN transcript_received_at timestamptz")
    op.execute("ALTER TABLE meetings ADD COLUMN asr_identity text")

    op.execute("ALTER TABLE meeting_segments DROP CONSTRAINT meeting_segments_source_check")
    op.execute(
        "ALTER TABLE meeting_segments ADD CONSTRAINT meeting_segments_source_check "
        "CHECK (source IN ('server_asr','device_asr'))"
    )

    op.execute("ALTER TABLE meeting_minutes ADD COLUMN provider text")
    op.execute("ALTER TABLE meeting_minutes ADD COLUMN prompt_sha256 text")

    op.execute("""CREATE TABLE tenant_ai_instructions (
        tenant_id uuid NOT NULL REFERENCES tenants(id),
        scope text NOT NULL CHECK (scope IN ('coach','meeting')),
        instructions text NOT NULL CHECK (char_length(instructions) <= 8000),
        updated_by_type text NOT NULL CHECK (updated_by_type IN ('user','staff')),
        updated_by uuid,
        updated_at timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (tenant_id, scope)
    )""")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON tenant_ai_instructions TO cbi_app")
    op.execute("ALTER TABLE tenant_ai_instructions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenant_ai_instructions FORCE ROW LEVEL SECURITY")
    op.execute("""CREATE POLICY tenant_ai_instructions_tenant_isolation ON tenant_ai_instructions
        USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
            OR current_setting('app.staff', true) = 'on')
        WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
            OR current_setting('app.staff', true) = 'on')""")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS tenant_ai_instructions")
    op.execute("ALTER TABLE meeting_minutes DROP COLUMN prompt_sha256")
    op.execute("ALTER TABLE meeting_minutes DROP COLUMN provider")
    # Device-sourced segments cannot satisfy the old constraint, so they are removed first.
    op.execute("DELETE FROM meeting_segments WHERE source = 'device_asr'")
    op.execute("ALTER TABLE meeting_segments DROP CONSTRAINT meeting_segments_source_check")
    op.execute(
        "ALTER TABLE meeting_segments ADD CONSTRAINT meeting_segments_source_check "
        "CHECK (source IN ('server_asr'))"
    )
    op.execute("ALTER TABLE meetings DROP COLUMN asr_identity")
    op.execute("ALTER TABLE meetings DROP COLUMN transcript_received_at")
    op.execute("ALTER TABLE meetings DROP COLUMN transcript_sha256")
    op.execute("ALTER TABLE meetings DROP CONSTRAINT meetings_input_kind_check")
    op.execute("ALTER TABLE meetings DROP COLUMN input_kind")
