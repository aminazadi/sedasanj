"""Store the net amount, tax and line items on invoices."""

from alembic import op

revision = "0066_invoice_tax_breakdown"
down_revision = "0065_sub_change_idempotency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE invoices ADD COLUMN net_toman bigint")
    op.execute("ALTER TABLE invoices ADD COLUMN tax_toman bigint NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE invoices ADD COLUMN tax_percent integer NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE invoices ADD COLUMN lines jsonb NOT NULL DEFAULT '[]'")
    op.execute("UPDATE invoices SET net_toman = amount_toman")
    op.execute("ALTER TABLE invoices ALTER COLUMN net_toman SET NOT NULL")
    op.execute(
        "ALTER TABLE invoices ADD CONSTRAINT invoices_tax_nonnegative_check "
        "CHECK (tax_toman >= 0 AND net_toman >= 0) NOT VALID"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE invoices DROP CONSTRAINT IF EXISTS invoices_tax_nonnegative_check")
    op.execute("ALTER TABLE invoices DROP COLUMN lines")
    op.execute("ALTER TABLE invoices DROP COLUMN tax_percent")
    op.execute("ALTER TABLE invoices DROP COLUMN tax_toman")
    op.execute("ALTER TABLE invoices DROP COLUMN net_toman")
