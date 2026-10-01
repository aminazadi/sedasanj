"""Add persistent assistant conversation archives.

Revision ID: 0027_assistant_ephemeral_and_archives
Revises: 0026_balance_cache_integrity
"""

from alembic import op

revision = "0027_assistant_ephemeral_and_archives"
down_revision = "0026_balance_cache_integrity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE chat_conversations ADD COLUMN archived_at timestamptz")
    op.execute(
        "CREATE INDEX idx_chat_conversations_archive "
        "ON chat_conversations (tenant_id, owner_id, archived_at, updated_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_chat_conversations_archive")
    op.execute("ALTER TABLE chat_conversations DROP COLUMN IF EXISTS archived_at")
