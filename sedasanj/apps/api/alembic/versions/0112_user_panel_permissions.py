"""Store optional per-user panel permissions in control and tenant databases."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0112_user_panel_permissions"
down_revision = "0111_ml_model_help_content"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("panel_permissions", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "panel_permissions")
