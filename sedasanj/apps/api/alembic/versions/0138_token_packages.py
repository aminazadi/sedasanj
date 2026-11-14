"""Purchasable LLM token packs (admin managed, sold through the normal order flow)."""

from alembic import op

revision = "0138_token_packages"
down_revision = "0137_payment_failure_codes_help"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE TABLE token_packages (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        name text NOT NULL,
        tokens bigint NOT NULL CHECK (tokens > 0),
        price_toman integer NOT NULL CHECK (price_toman > 0),
        active boolean NOT NULL DEFAULT true,
        created_at timestamptz NOT NULL DEFAULT now()
    )""")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON token_packages TO cbi_app")


def downgrade() -> None:
    op.execute("DROP TABLE token_packages")
