"""Persist assistant message context attachments.

Revision ID: 0036_chat_message_attachments
Revises: 0035_user_profile_context
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0036_chat_message_attachments"
down_revision = "0035_user_profile_context"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "chat_messages",
        sa.Column("attachments", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("chat_messages", "attachments")
