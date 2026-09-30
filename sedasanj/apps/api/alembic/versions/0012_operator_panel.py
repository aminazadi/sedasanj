"""Operator numbers and per-tenant operator quota.

Revision ID: 0012_operator_panel
Revises: 0011
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0012_operator_panel"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE tenants ADD COLUMN max_operators integer NOT NULL DEFAULT 5")
    op.execute(
        "ALTER TABLE tenants ADD CONSTRAINT tenants_max_operators_check CHECK (max_operators >= 0)"
    )
    op.execute("ALTER TABLE users ADD COLUMN mobile_number text")
    op.execute("ALTER TABLE users ADD COLUMN extension text")
    op.execute(
        "CREATE UNIQUE INDEX users_tenant_extension_key "
        "ON users (tenant_id, extension) "
        "WHERE extension IS NOT NULL AND btrim(extension) <> ''"
    )
    op.execute(
        "CREATE UNIQUE INDEX users_tenant_mobile_key "
        "ON users (tenant_id, mobile_number) "
        "WHERE mobile_number IS NOT NULL AND btrim(mobile_number) <> ''"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS users_tenant_mobile_key")
    op.execute("DROP INDEX IF EXISTS users_tenant_extension_key")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS extension")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS mobile_number")
    op.execute("ALTER TABLE tenants DROP CONSTRAINT IF EXISTS tenants_max_operators_check")
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS max_operators")
