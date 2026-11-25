"""Jalase-Negar rewards: event-based XP, acknowledged badges, idempotent gift grants.

`jalase_xp_events` records each meeting and finished document once, so deleting a meeting no
longer lowers the level.  `jalase_earned_achievements.notified_at` lets the app tell which badges
it has already shown.  The partial unique index makes a repeated gift grant for the same invite
or badge a no-op instead of a second payment.
"""

from alembic import op

revision = "0161_jalase_rewards_events"
down_revision = "0160_jalase_output_type_icon"
branch_labels = None
depends_on = None

POLICY = """USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
            OR current_setting('app.staff', true) = 'on')
        WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
            OR current_setting('app.staff', true) = 'on')"""


def upgrade() -> None:
    op.execute("ALTER TABLE jalase_earned_achievements ADD COLUMN notified_at timestamptz")
    # Badges earned before this release were already shown by the old progress screen; do not
    # present all of them as new on the first open after the upgrade.
    op.execute("UPDATE jalase_earned_achievements SET notified_at = earned_at")
    # Older double-paid invite gifts (the race this release fixes) keep the first grant only.
    op.execute(
        """DELETE FROM token_grants extra
           USING token_grants first
           WHERE extra.source_id IS NOT NULL
             AND first.source_id IS NOT NULL
             AND extra.tenant_id = first.tenant_id
             AND extra.source = first.source
             AND extra.source_id = first.source_id
             AND (extra.created_at, extra.id) > (first.created_at, first.id)"""
    )
    op.execute(
        "CREATE UNIQUE INDEX token_grants_source_unique "
        "ON token_grants (tenant_id, source, source_id) WHERE source_id IS NOT NULL"
    )
    op.execute("""CREATE TABLE jalase_xp_events (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id uuid NOT NULL REFERENCES tenants(id),
        kind varchar(16) NOT NULL CHECK (kind IN ('meeting','document')),
        ref_id uuid NOT NULL,
        points integer NOT NULL CHECK (points > 0),
        created_at timestamptz NOT NULL DEFAULT now(),
        UNIQUE (tenant_id, kind, ref_id))""")
    op.execute("CREATE INDEX idx_jalase_xp_tenant ON jalase_xp_events (tenant_id)")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON jalase_xp_events TO cbi_app")
    op.execute("ALTER TABLE jalase_xp_events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE jalase_xp_events FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY jalase_xp_events_tenant_isolation ON jalase_xp_events {POLICY}")
    op.execute(
        "INSERT INTO jalase_xp_events (tenant_id, kind, ref_id, points) "
        "SELECT tenant_id, 'meeting', id, 10 FROM meetings WHERE status = 'complete' "
        "ON CONFLICT DO NOTHING"
    )
    op.execute(
        "INSERT INTO jalase_xp_events (tenant_id, kind, ref_id, points) "
        "SELECT tenant_id, 'document', id, 5 FROM meeting_documents WHERE status = 'done' "
        "ON CONFLICT DO NOTHING"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS jalase_xp_events")
    op.execute("DROP INDEX IF EXISTS token_grants_source_unique")
    op.execute("ALTER TABLE jalase_earned_achievements DROP COLUMN IF EXISTS notified_at")
