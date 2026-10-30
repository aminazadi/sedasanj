"""Multi-gateway payments: wider tokens, per-gateway uniqueness, reconciliation columns."""

from alembic import op

revision = "0062_payment_gateways"
down_revision = "0061_assistant_exports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE payment_attempts DROP CONSTRAINT IF EXISTS payment_attempts_authority_key"
    )
    op.execute("ALTER TABLE payment_attempts ALTER COLUMN authority TYPE varchar(255)")
    op.execute("ALTER TABLE payment_attempts ALTER COLUMN ref_id TYPE varchar(128)")
    op.execute("ALTER TABLE payment_attempts ADD COLUMN order_ref bigint")
    op.execute("ALTER TABLE payment_attempts ADD COLUMN rrn varchar(64)")
    op.execute("ALTER TABLE payment_attempts ADD COLUMN card_pan varchar(32)")
    op.execute("ALTER TABLE payment_attempts ADD COLUMN failure_code varchar(64)")
    op.execute("ALTER TABLE payment_attempts ADD COLUMN callback_json jsonb NOT NULL DEFAULT '{}'")
    op.execute("ALTER TABLE payment_attempts ADD COLUMN check_count integer NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE payment_attempts ADD COLUMN last_checked_at timestamptz")
    op.execute("ALTER TABLE payment_attempts ADD COLUMN settled_at timestamptz")
    op.execute(
        "ALTER TABLE payment_attempts ADD COLUMN updated_at timestamptz NOT NULL DEFAULT now()"
    )
    op.execute(
        "CREATE UNIQUE INDEX payment_attempts_gateway_authority_key "
        "ON payment_attempts (gateway, authority) WHERE authority IS NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX payment_attempts_gateway_order_ref_key "
        "ON payment_attempts (gateway, order_ref) WHERE order_ref IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX idx_payment_attempts_open ON payment_attempts (status, created_at) "
        "WHERE status IN ('redirected','pending_verification','verified')"
    )
    op.execute(
        "ALTER TABLE payment_attempts DROP CONSTRAINT IF EXISTS payment_attempts_status_check"
    )
    op.execute(
        "ALTER TABLE payment_attempts ADD CONSTRAINT payment_attempts_status_check CHECK "
        "(status IN ('redirected','canceled','pending_verification','failed','verified',"
        "'expired','superseded'))"
    )
    op.execute("UPDATE payment_attempts SET settled_at = verified_at WHERE status = 'verified'")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_payment_attempts_open")
    op.execute("DROP INDEX IF EXISTS payment_attempts_gateway_order_ref_key")
    op.execute("DROP INDEX IF EXISTS payment_attempts_gateway_authority_key")
    op.execute(
        "ALTER TABLE payment_attempts DROP CONSTRAINT IF EXISTS payment_attempts_status_check"
    )
    op.execute(
        "UPDATE payment_attempts SET status = 'failed' WHERE status IN ('expired','superseded')"
    )
    op.execute(
        "ALTER TABLE payment_attempts ADD CONSTRAINT payment_attempts_status_check CHECK "
        "(status IN ('redirected','canceled','pending_verification','failed','verified'))"
    )
    for column in (
        "updated_at",
        "settled_at",
        "last_checked_at",
        "check_count",
        "callback_json",
        "failure_code",
        "card_pan",
        "rrn",
        "order_ref",
    ):
        op.execute(f"ALTER TABLE payment_attempts DROP COLUMN {column}")
    op.execute("ALTER TABLE payment_attempts ALTER COLUMN ref_id TYPE varchar(64)")
    op.execute("ALTER TABLE payment_attempts ALTER COLUMN authority TYPE varchar(64)")
    op.execute(
        "ALTER TABLE payment_attempts ADD CONSTRAINT payment_attempts_authority_key "
        "UNIQUE (authority)"
    )
