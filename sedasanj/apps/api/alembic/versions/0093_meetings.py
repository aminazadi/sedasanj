"""Meetings: chunked recordings from the Jalase-Negar app, analysed server side.

Adds the meeting tables, per-user mobile API keys and meeting-aware billing columns.
"""

from alembic import op

revision = "0093_meetings"
down_revision = "0092_contacts_import_no_pause"
branch_labels = None
depends_on = None

# Tenant data tables, in dependency order (children last on drop).
TENANT_TABLES = (
    "meetings",
    "meeting_chunks",
    "meeting_segments",
    "meeting_chunk_speakers",
    "meeting_speakers",
    "meeting_analysis_steps",
    "meeting_minutes",
    "meeting_events",
)
# Pairing codes are redeemed before the tenant is known, so they live in the control database.
CONTROL_TABLES = ("meeting_pairing_codes",)

MEETING_STATUSES = (
    "'receiving','processing','complete','failed_retryable','failed_terminal','canceled'"
)
CHUNK_STATUSES = "'received','queued','transcribing','transcribed','failed'"
STEP_KINDS = "'block_summary','final_minutes','extract','repair'"
STEP_STATUSES = "'pending','running','done','failed'"


def _rls(table: str) -> None:
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO cbi_app")
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"""CREATE POLICY {table}_tenant_isolation ON {table}
        USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
            OR current_setting('app.staff', true) = 'on')
        WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
            OR current_setting('app.staff', true) = 'on')""")


def upgrade() -> None:
    op.execute(
        "ALTER TABLE api_keys ADD COLUMN user_id uuid REFERENCES users(id) ON DELETE CASCADE"
    )
    op.execute("ALTER TABLE api_keys ADD COLUMN kind text NOT NULL DEFAULT 'integration'")
    op.execute(
        "ALTER TABLE api_keys ADD CONSTRAINT api_keys_kind_check "
        "CHECK (kind IN ('integration','mobile'))"
    )
    op.execute(
        "ALTER TABLE api_keys ADD CONSTRAINT api_keys_mobile_user_check "
        "CHECK (kind <> 'mobile' OR user_id IS NOT NULL)"
    )
    op.execute(
        "CREATE INDEX idx_api_keys_mobile_user ON api_keys (user_id, created_at) "
        "WHERE kind = 'mobile'"
    )

    op.execute(f"""CREATE TABLE meetings (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id uuid NOT NULL REFERENCES tenants(id),
        owner_user_id uuid NOT NULL REFERENCES users(id),
        client_meeting_id uuid NOT NULL,
        title text,
        status text NOT NULL DEFAULT 'receiving' CHECK (status IN ({MEETING_STATUSES})),
        started_at timestamptz NOT NULL,
        ended_at timestamptz,
        finish_requested_at timestamptz,
        duration_ms bigint,
        sample_rate integer NOT NULL DEFAULT 16000,
        channels smallint NOT NULL DEFAULT 1,
        app_version text,
        total_chunks integer,
        received_chunks integer NOT NULL DEFAULT 0,
        processed_chunks integer NOT NULL DEFAULT 0,
        received_ms bigint NOT NULL DEFAULT 0,
        reserved_seconds integer NOT NULL DEFAULT 0,
        reserved_blocks integer NOT NULL DEFAULT 0,
        billed_seconds integer,
        speaker_count integer,
        error_code text,
        progress_pct smallint NOT NULL DEFAULT 0 CHECK (progress_pct BETWEEN 0 AND 100),
        progress_detail text,
        audio_id uuid REFERENCES audio_objects(id) ON DELETE SET NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT meetings_client_unique UNIQUE (tenant_id, client_meeting_id)
    )""")
    op.execute(
        "CREATE INDEX idx_meetings_owner ON meetings (tenant_id, owner_user_id, started_at DESC)"
    )
    op.execute("CREATE INDEX idx_meetings_tenant_started ON meetings (tenant_id, started_at DESC)")
    op.execute("CREATE INDEX idx_meetings_status ON meetings (status, updated_at)")

    op.execute(f"""CREATE TABLE meeting_chunks (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id uuid NOT NULL REFERENCES tenants(id),
        meeting_id uuid NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
        seq integer NOT NULL CHECK (seq >= 0),
        t_start_ms bigint NOT NULL CHECK (t_start_ms >= 0),
        t_end_ms bigint NOT NULL CHECK (t_end_ms >= t_start_ms),
        audio_id uuid REFERENCES audio_objects(id) ON DELETE SET NULL,
        sha256 text NOT NULL,
        bytes bigint NOT NULL,
        duration_ms integer NOT NULL DEFAULT 0,
        device_text jsonb,
        status text NOT NULL DEFAULT 'received' CHECK (status IN ({CHUNK_STATUSES})),
        attempts integer NOT NULL DEFAULT 0,
        error_code text,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT meeting_chunks_seq_unique UNIQUE (meeting_id, seq)
    )""")
    op.execute("CREATE INDEX idx_meeting_chunks_status ON meeting_chunks (status, updated_at)")

    op.execute("""CREATE TABLE meeting_segments (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id uuid NOT NULL REFERENCES tenants(id),
        meeting_id uuid NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
        chunk_id uuid REFERENCES meeting_chunks(id) ON DELETE CASCADE,
        t_start_ms bigint NOT NULL,
        t_end_ms bigint NOT NULL,
        speaker_idx smallint,
        text text NOT NULL,
        source text NOT NULL DEFAULT 'server_asr' CHECK (source IN ('server_asr'))
    )""")
    op.execute(
        "CREATE INDEX idx_meeting_segments_time ON meeting_segments (meeting_id, t_start_ms)"
    )
    op.execute("CREATE INDEX idx_meeting_segments_chunk ON meeting_segments (chunk_id)")

    op.execute("""CREATE TABLE meeting_chunk_speakers (
        tenant_id uuid NOT NULL REFERENCES tenants(id),
        chunk_id uuid NOT NULL REFERENCES meeting_chunks(id) ON DELETE CASCADE,
        local_idx smallint NOT NULL,
        speech_ms integer NOT NULL DEFAULT 0,
        embedding bytea,
        PRIMARY KEY (chunk_id, local_idx)
    )""")

    op.execute("""CREATE TABLE meeting_speakers (
        tenant_id uuid NOT NULL REFERENCES tenants(id),
        meeting_id uuid NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
        speaker_idx smallint NOT NULL,
        label text NOT NULL,
        user_id uuid REFERENCES users(id) ON DELETE SET NULL,
        total_ms bigint NOT NULL DEFAULT 0,
        PRIMARY KEY (meeting_id, speaker_idx)
    )""")

    op.execute(f"""CREATE TABLE meeting_analysis_steps (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id uuid NOT NULL REFERENCES tenants(id),
        meeting_id uuid NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
        kind text NOT NULL CHECK (kind IN ({STEP_KINDS})),
        ordinal integer NOT NULL DEFAULT 0,
        idempotency_key text NOT NULL UNIQUE,
        status text NOT NULL DEFAULT 'pending' CHECK (status IN ({STEP_STATUSES})),
        input_digest text,
        output jsonb,
        attempts integer NOT NULL DEFAULT 0,
        error_code text,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now()
    )""")
    op.execute(
        "CREATE INDEX idx_meeting_steps_meeting "
        "ON meeting_analysis_steps (meeting_id, kind, ordinal)"
    )

    op.execute("""CREATE TABLE meeting_minutes (
        tenant_id uuid NOT NULL REFERENCES tenants(id),
        meeting_id uuid NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
        version integer NOT NULL CHECK (version >= 1),
        content_md text NOT NULL,
        structured jsonb,
        model text,
        is_selected boolean NOT NULL DEFAULT false,
        created_at timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (meeting_id, version)
    )""")

    op.execute("""CREATE TABLE meeting_events (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id uuid NOT NULL REFERENCES tenants(id),
        meeting_id uuid NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
        step_key text NOT NULL,
        kind text NOT NULL,
        status text NOT NULL,
        detail text,
        created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT meeting_events_step_unique UNIQUE (meeting_id, step_key)
    )""")
    op.execute("CREATE INDEX idx_meeting_events_meeting ON meeting_events (meeting_id, created_at)")

    op.execute("""CREATE TABLE meeting_pairing_codes (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id uuid NOT NULL REFERENCES tenants(id),
        user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        code_hash text NOT NULL UNIQUE,
        label text,
        expires_at timestamptz NOT NULL,
        used_at timestamptz,
        created_at timestamptz NOT NULL DEFAULT now()
    )""")
    op.execute(
        "CREATE INDEX idx_meeting_pairing_user ON meeting_pairing_codes (user_id, created_at)"
    )

    for table in (*TENANT_TABLES, *CONTROL_TABLES):
        _rls(table)

    op.execute("ALTER TABLE credit_reservations ALTER COLUMN call_id DROP NOT NULL")
    op.execute(
        "ALTER TABLE credit_reservations ADD COLUMN meeting_id uuid "
        "REFERENCES meetings(id) ON DELETE CASCADE"
    )
    op.execute(
        "ALTER TABLE credit_reservations ADD CONSTRAINT credit_reservations_target_check "
        "CHECK (num_nonnulls(call_id, meeting_id) = 1)"
    )
    op.execute(
        "CREATE INDEX idx_credit_reservations_meeting ON credit_reservations (meeting_id) "
        "WHERE meeting_id IS NOT NULL"
    )
    op.execute("ALTER TABLE ledger_entries ADD COLUMN meeting_id uuid")
    op.execute(
        "CREATE INDEX idx_ledger_meeting ON ledger_entries (meeting_id) "
        "WHERE meeting_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX idx_ledger_meeting")
    op.execute("ALTER TABLE ledger_entries DROP COLUMN meeting_id")
    # Meeting reservations have no call to point at once the column is mandatory again.
    op.execute("DELETE FROM credit_reservations WHERE call_id IS NULL")
    op.execute("DROP INDEX idx_credit_reservations_meeting")
    op.execute("ALTER TABLE credit_reservations DROP CONSTRAINT credit_reservations_target_check")
    op.execute("ALTER TABLE credit_reservations DROP COLUMN meeting_id")
    op.execute("ALTER TABLE credit_reservations ALTER COLUMN call_id SET NOT NULL")
    for table in reversed((*TENANT_TABLES, *CONTROL_TABLES)):
        op.execute(f"DROP TABLE {table}")
    op.execute("DELETE FROM api_keys WHERE kind = 'mobile'")
    op.execute("DROP INDEX idx_api_keys_mobile_user")
    op.execute("ALTER TABLE api_keys DROP CONSTRAINT api_keys_mobile_user_check")
    op.execute("ALTER TABLE api_keys DROP CONSTRAINT api_keys_kind_check")
    op.execute("ALTER TABLE api_keys DROP COLUMN kind")
    op.execute("ALTER TABLE api_keys DROP COLUMN user_id")
