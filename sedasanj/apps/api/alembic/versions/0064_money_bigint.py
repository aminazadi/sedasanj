"""Widen order, invoice, ledger and balance money columns to bigint and forbid negative amounts."""

from alembic import op

revision = "0064_money_bigint"
down_revision = "0063_plan_monthly_default"
branch_labels = None
depends_on = None

_COLUMNS = (
    ("orders", "amount_toman"),
    ("order_items", "unit_price_toman"),
    ("order_items", "total_toman"),
    ("invoices", "amount_toman"),
    ("refunds", "amount_toman"),
    ("ledger_entries", "toman_delta"),
    ("credit_reservations", "toman"),
    ("tenant_balance_cache", "toman"),
    ("subscription_extras", "unit_price_toman"),
)


def upgrade() -> None:
    for table, column in _COLUMNS:
        op.execute(f"ALTER TABLE {table} ALTER COLUMN {column} TYPE bigint")
    # NOT VALID: new and updated rows are checked without scanning legacy rows on deploy.
    op.execute(
        "ALTER TABLE orders ADD CONSTRAINT orders_amount_nonnegative_check "
        "CHECK (amount_toman >= 0) NOT VALID"
    )
    op.execute(
        "ALTER TABLE invoices ADD CONSTRAINT invoices_amount_nonnegative_check "
        "CHECK (amount_toman >= 0) NOT VALID"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE invoices DROP CONSTRAINT IF EXISTS invoices_amount_nonnegative_check")
    op.execute("ALTER TABLE orders DROP CONSTRAINT IF EXISTS orders_amount_nonnegative_check")
    for table, column in reversed(_COLUMNS):
        op.execute(f"ALTER TABLE {table} ALTER COLUMN {column} TYPE integer")
