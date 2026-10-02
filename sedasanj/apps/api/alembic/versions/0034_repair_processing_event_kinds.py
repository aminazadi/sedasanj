"""Repair the processing event kind constraint.

Revision ID: 0034_repair_processing_event_kinds
Revises: 0033_repair_assistant_indexes
"""

from alembic import op

revision = "0034_repair_processing_event_kinds"
down_revision = "0033_repair_assistant_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE processing_events "
        "DROP CONSTRAINT IF EXISTS processing_events_kind_check"
    )
    op.execute(
        "ALTER TABLE processing_events "
        "ADD CONSTRAINT processing_events_kind_check "
        "CHECK (kind IN ('pipeline','asr','emotion','correction','llm','notify'))"
    )


def downgrade() -> None:
    op.execute("DELETE FROM processing_events WHERE kind = 'correction'")
    op.execute(
        "ALTER TABLE processing_events "
        "DROP CONSTRAINT IF EXISTS processing_events_kind_check"
    )
    op.execute(
        "ALTER TABLE processing_events "
        "ADD CONSTRAINT processing_events_kind_check "
        "CHECK (kind IN ('pipeline','asr','emotion','llm','notify'))"
    )
