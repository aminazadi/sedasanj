"""Ensure all call-owned records can be removed with the call.

Revision ID: 0015_call_deletion_integrity
Revises: 0014_merge_heads
"""

from __future__ import annotations

from alembic import op

revision = "0015_call_deletion_integrity"
down_revision = "0014_merge_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE credit_reservations "
        "DROP CONSTRAINT IF EXISTS credit_reservations_call_id_fkey"
    )
    op.execute(
        "ALTER TABLE credit_reservations "
        "ADD CONSTRAINT credit_reservations_call_id_fkey "
        "FOREIGN KEY (call_id) REFERENCES calls(id) ON DELETE CASCADE"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE credit_reservations "
        "DROP CONSTRAINT IF EXISTS credit_reservations_call_id_fkey"
    )
    op.execute(
        "ALTER TABLE credit_reservations "
        "ADD CONSTRAINT credit_reservations_call_id_fkey "
        "FOREIGN KEY (call_id) REFERENCES calls(id)"
    )
