"""Add control-plane phone challenges and scoped quick-demo sessions."""

from alembic import op

revision = "0048_quick_demo"
down_revision = "0047_voicemail_calls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE phone_otps (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            mobile varchar(20) NOT NULL,
            code_hash text NOT NULL,
            attempts integer NOT NULL DEFAULT 0,
            expires_at timestamptz NOT NULL,
            verified_at timestamptz,
            grant_hash varchar(64) UNIQUE,
            grant_expires_at timestamptz,
            consumed_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_phone_otps_mobile ON phone_otps(mobile)")
    op.execute("""
        CREATE TABLE quick_demo_sessions (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenants(id),
            user_id uuid NOT NULL REFERENCES users(id),
            mobile varchar(20) NOT NULL,
            token_hash varchar(64) UNIQUE NOT NULL,
            expires_at timestamptz NOT NULL,
            max_duration_seconds integer NOT NULL,
            duration_ms integer,
            call_id uuid,
            upload_attempt integer NOT NULL DEFAULT 0,
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_quick_demo_sessions_mobile ON quick_demo_sessions(mobile)")
    for table in ("phone_otps", "quick_demo_sessions"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_staff ON {table} FOR ALL "
            "USING (current_setting('app.staff', true) = 'on') "
            "WITH CHECK (current_setting('app.staff', true) = 'on')"
        )
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO cbi_app")


def downgrade() -> None:
    op.execute("DROP TABLE quick_demo_sessions")
    op.execute("DROP TABLE phone_otps")
