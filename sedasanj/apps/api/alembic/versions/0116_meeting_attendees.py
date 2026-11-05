"""Meeting attendees: the people a Jalase-Negar user marked as present before recording.

One row per person per meeting. `profile_client_id` is the app's own id for the person and is
always kept; `profile_id` points at the synced speaker profile once the server knows it (it is
empty when the phone had not synced that person yet, or the person is later deleted). `name` is
a snapshot so the panel and the minutes still show who was there.
"""

from alembic import op

revision = "0116_meeting_attendees"
down_revision = "0115_jalase_negar_install_help"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE TABLE meeting_attendees (
        tenant_id uuid NOT NULL REFERENCES tenants(id),
        meeting_id uuid NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
        profile_client_id uuid NOT NULL,
        profile_id uuid REFERENCES speaker_profiles(id) ON DELETE SET NULL,
        name text NOT NULL CHECK (char_length(name) BETWEEN 1 AND 80),
        created_at timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (meeting_id, profile_client_id)
    )""")
    op.execute("CREATE INDEX idx_meeting_attendees_tenant ON meeting_attendees (tenant_id)")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON meeting_attendees TO cbi_app")
    op.execute("ALTER TABLE meeting_attendees ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE meeting_attendees FORCE ROW LEVEL SECURITY")
    op.execute("""CREATE POLICY meeting_attendees_tenant_isolation ON meeting_attendees
        USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
            OR current_setting('app.staff', true) = 'on')
        WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
            OR current_setting('app.staff', true) = 'on')""")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS meeting_attendees")
