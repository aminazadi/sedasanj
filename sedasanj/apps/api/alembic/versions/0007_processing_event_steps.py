"""Make processing timeline entries stateful per job step.

Revision ID: 0007_processing_event_steps
Revises: 0006_processing_events
"""

from __future__ import annotations

from alembic import op

revision = "0007_processing_event_steps"
down_revision = "0006_processing_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE processing_events ADD COLUMN step_key text")
    op.execute(
        "CREATE UNIQUE INDEX uq_processing_events_call_step "
        "ON processing_events (call_id, step_key) WHERE step_key IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_processing_events_call_step")
    op.execute("ALTER TABLE processing_events DROP COLUMN IF EXISTS step_key")
