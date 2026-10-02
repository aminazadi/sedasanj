"""Add user profile context for personalized assistant responses.

Revision ID: 0035_user_profile_context
Revises: 0034_repair_processing_event_kinds
"""

from alembic import op
import sqlalchemy as sa

revision = "0035_user_profile_context"
down_revision = "0034_repair_processing_event_kinds"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("profile_context", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "profile_context")
