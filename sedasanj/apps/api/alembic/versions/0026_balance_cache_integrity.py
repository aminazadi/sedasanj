"""Repair tenant balance cache nulls and enforce numeric defaults.

Revision ID: 0026_balance_cache_integrity
Revises: 0025_sales_kpi_center
"""

from alembic import op

revision = "0026_balance_cache_integrity"
down_revision = "0025_sales_kpi_center"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE tenant_balance_cache SET seconds = 0 WHERE seconds IS NULL")
    op.execute("UPDATE tenant_balance_cache SET toman = 0 WHERE toman IS NULL")
    op.execute("ALTER TABLE tenant_balance_cache ALTER COLUMN seconds SET DEFAULT 0")
    op.execute("ALTER TABLE tenant_balance_cache ALTER COLUMN toman SET DEFAULT 0")
    op.execute("ALTER TABLE tenant_balance_cache ALTER COLUMN seconds SET NOT NULL")
    op.execute("ALTER TABLE tenant_balance_cache ALTER COLUMN toman SET NOT NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE tenant_balance_cache ALTER COLUMN seconds DROP DEFAULT")
    op.execute("ALTER TABLE tenant_balance_cache ALTER COLUMN toman DROP DEFAULT")
