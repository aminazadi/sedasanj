"""Make assistant message ordering deterministic.

Revision ID: 0042_chat_message_ordinal
Revises: 0041_direct_ninerouter_provider
"""

from alembic import op

revision = "0042_chat_message_ordinal"
down_revision = "0041_direct_ninerouter_provider"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SEQUENCE IF NOT EXISTS chat_messages_ordinal_seq")
    op.execute("ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS ordinal bigint")
    op.execute(
        "ALTER TABLE chat_messages ALTER COLUMN ordinal SET DEFAULT "
        "nextval('chat_messages_ordinal_seq')"
    )
    op.execute(
        "UPDATE chat_messages SET ordinal = nextval('chat_messages_ordinal_seq') "
        "WHERE ordinal IS NULL"
    )
    op.execute("ALTER TABLE chat_messages ALTER COLUMN ordinal SET NOT NULL")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_chat_messages_conversation_ordinal "
        "ON chat_messages (conversation_id, ordinal)"
    )
    op.execute("DROP INDEX IF EXISTS idx_chat_messages_conversation")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_chat_messages_conversation "
        "ON chat_messages (conversation_id, ordinal)"
    )
    op.execute("GRANT USAGE, SELECT ON SEQUENCE chat_messages_ordinal_seq TO cbi_app")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_chat_messages_conversation_ordinal")
    op.execute("DROP INDEX IF EXISTS idx_chat_messages_conversation")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_chat_messages_conversation "
        "ON chat_messages (conversation_id, created_at)"
    )
    op.execute("ALTER TABLE chat_messages DROP COLUMN IF EXISTS ordinal")
    op.execute("DROP SEQUENCE IF EXISTS chat_messages_ordinal_seq")
