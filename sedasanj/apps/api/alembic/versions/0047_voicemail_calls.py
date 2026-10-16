"""Add voicemail call metadata and classification.

Revision ID: 0047_voicemail_calls
Revises: 0046_call_dispositions
"""

from alembic import op

revision = "0047_voicemail_calls"
down_revision = "0046_call_dispositions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE calls DROP CONSTRAINT IF EXISTS calls_call_type_check")
    op.execute(
        "ALTER TABLE calls ADD CONSTRAINT calls_call_type_check CHECK "
        "(call_type IN ('answered','no_answer','busy','congestion','failed','canceled','voicemail'))"
    )
    op.execute("ALTER TABLE calls ADD COLUMN voicemail_context text")
    op.execute("ALTER TABLE calls ADD COLUMN voicemail_folder text")
    op.execute("ALTER TABLE calls ADD COLUMN voicemail_message_id text")


def downgrade() -> None:
    op.execute("UPDATE calls SET call_type = 'no_answer' WHERE call_type = 'voicemail'")
    op.execute("ALTER TABLE calls DROP COLUMN voicemail_message_id")
    op.execute("ALTER TABLE calls DROP COLUMN voicemail_folder")
    op.execute("ALTER TABLE calls DROP COLUMN voicemail_context")
    op.execute("ALTER TABLE calls DROP CONSTRAINT IF EXISTS calls_call_type_check")
    op.execute(
        "ALTER TABLE calls ADD CONSTRAINT calls_call_type_check CHECK "
        "(call_type IN ('answered','no_answer','busy','congestion','failed','canceled'))"
    )
