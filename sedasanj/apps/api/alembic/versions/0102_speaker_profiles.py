"""Jalase-Negar speaker profiles: people and their encrypted voiceprints, synced across devices.

A profile is one person a user defined in the app; its voiceprints are the embeddings the app
computed on the phone from that person reading the enrolment texts. The server only stores and
syncs them (encrypted at rest, see `app/services/voiceprint_crypto.py`); it never needs the audio.

`speaker_sync_state` hands out the per-tenant change counter that clients page with. Taking the
counter row's lock for the rest of the transaction makes counter order equal commit order, so a
client that has seen counter N can never miss a row that commits later with a smaller number.
Meeting segments also learn whether a line was spoken over another voice and how sure the
on-device match was, and meeting speakers can point at the profile they were matched to.
"""

from alembic import op

revision = "0102_speaker_profiles"
down_revision = "0101_report_documents"
branch_labels = None
depends_on = None

# Tenant data tables, in dependency order (children last on drop).
TENANT_TABLES = ("speaker_sync_state", "speaker_profiles", "speaker_voiceprints")


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
    op.execute("""CREATE TABLE speaker_sync_state (
        tenant_id uuid PRIMARY KEY REFERENCES tenants(id),
        seq bigint NOT NULL DEFAULT 0
    )""")

    op.execute("""CREATE TABLE speaker_profiles (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id uuid NOT NULL REFERENCES tenants(id),
        owner_user_id uuid NOT NULL REFERENCES users(id),
        client_id uuid NOT NULL,
        display_name text NOT NULL CHECK (char_length(display_name) BETWEEN 1 AND 80),
        visibility text NOT NULL DEFAULT 'private' CHECK (visibility IN ('private','org')),
        was_shared boolean NOT NULL DEFAULT false,
        version integer NOT NULL DEFAULT 1 CHECK (version >= 1),
        change_seq bigint NOT NULL,
        consent_at timestamptz,
        consent_version text,
        deleted_at timestamptz,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT speaker_profiles_client_unique UNIQUE (tenant_id, client_id)
    )""")
    op.execute(
        "CREATE INDEX idx_speaker_profiles_changes ON speaker_profiles (tenant_id, change_seq)"
    )
    op.execute(
        "CREATE INDEX idx_speaker_profiles_owner ON speaker_profiles (tenant_id, owner_user_id) "
        "WHERE deleted_at IS NULL"
    )

    op.execute("""CREATE TABLE speaker_voiceprints (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id uuid NOT NULL REFERENCES tenants(id),
        profile_id uuid NOT NULL REFERENCES speaker_profiles(id) ON DELETE CASCADE,
        client_id uuid NOT NULL,
        model_id text NOT NULL,
        model_version text NOT NULL,
        dim smallint NOT NULL CHECK (dim BETWEEN 16 AND 2048),
        embedding bytea NOT NULL,
        quality smallint CHECK (quality BETWEEN 0 AND 100),
        duration_ms integer CHECK (duration_ms >= 0),
        created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT speaker_voiceprints_sample_unique UNIQUE (profile_id, client_id, model_id)
    )""")
    op.execute("CREATE INDEX idx_speaker_voiceprints_profile ON speaker_voiceprints (profile_id)")

    for table in TENANT_TABLES:
        _rls(table)

    op.execute("ALTER TABLE meeting_segments ADD COLUMN overlap boolean NOT NULL DEFAULT false")
    op.execute("ALTER TABLE meeting_segments ADD COLUMN speaker_confidence smallint")
    op.execute(
        "ALTER TABLE meeting_segments ADD CONSTRAINT meeting_segments_confidence_check "
        "CHECK (speaker_confidence IS NULL OR speaker_confidence BETWEEN 0 AND 100)"
    )
    op.execute(
        "ALTER TABLE meeting_speakers ADD COLUMN profile_id uuid "
        "REFERENCES speaker_profiles(id) ON DELETE SET NULL"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE meeting_speakers DROP COLUMN IF EXISTS profile_id")
    op.execute(
        "ALTER TABLE meeting_segments DROP CONSTRAINT IF EXISTS meeting_segments_confidence_check"
    )
    op.execute("ALTER TABLE meeting_segments DROP COLUMN IF EXISTS speaker_confidence")
    op.execute("ALTER TABLE meeting_segments DROP COLUMN IF EXISTS overlap")
    for table in reversed(TENANT_TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table}")
