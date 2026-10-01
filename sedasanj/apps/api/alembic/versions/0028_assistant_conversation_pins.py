"""Add assistant conversation pins.

Revision ID: 0028_assistant_conversation_pins
Revises: 0027_assistant_ephemeral_and_archives
"""

from alembic import op

revision = "0028_assistant_conversation_pins"
down_revision = "0027_assistant_ephemeral_and_archives"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE chat_conversations ADD COLUMN pinned_at timestamptz")
    op.execute(
        "CREATE INDEX idx_chat_conversations_pin "
        "ON chat_conversations (tenant_id, owner_id, pinned_at DESC) "
        "WHERE pinned_at IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_chat_conversations_pin")
    op.execute("ALTER TABLE chat_conversations DROP COLUMN IF EXISTS pinned_at")
