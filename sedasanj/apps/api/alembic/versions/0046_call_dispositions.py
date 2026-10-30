"""Distinguish unanswered call dispositions.

Revision ID: 0046_call_dispositions
Revises: 0045_missed_calls
"""

import sqlalchemy as sa

from alembic import op

revision = "0046_call_dispositions"
down_revision = "0045_missed_calls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE calls SET call_type = 'no_answer' WHERE call_type = 'missed'")
    op.execute("ALTER TABLE calls DROP CONSTRAINT IF EXISTS calls_call_type_check")
    op.execute(
        "ALTER TABLE calls ADD CONSTRAINT calls_call_type_check CHECK "
        "(call_type IN ('answered','no_answer','busy','congestion','failed','canceled'))"
    )
    op.create_index(
        "idx_calls_tenant_call_type_started",
        "calls",
        ["tenant_id", "call_type", sa.text("started_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("idx_calls_tenant_call_type_started", table_name="calls")
    op.execute("ALTER TABLE calls DROP CONSTRAINT IF EXISTS calls_call_type_check")
    op.execute("UPDATE calls SET call_type = 'missed' WHERE call_type <> 'answered'")
    op.execute(
        "ALTER TABLE calls ADD CONSTRAINT calls_call_type_check "
        "CHECK (call_type IN ('answered','missed'))"
    )
