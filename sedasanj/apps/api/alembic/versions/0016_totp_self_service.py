"""Add TOTP enrollment for organization and service administrators."""
import sqlalchemy as sa

from alembic import op

revision = "0016_totp_self_service"
down_revision = "0015_call_deletion_integrity"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column("users", sa.Column("totp_pending_secret", sa.Text(), nullable=True))
    op.add_column("staff_users", sa.Column("totp_secret", sa.Text(), nullable=True))
    op.add_column("staff_users", sa.Column("totp_pending_secret", sa.Text(), nullable=True))

def downgrade() -> None:
    op.drop_column("staff_users", "totp_pending_secret")
    op.drop_column("staff_users", "totp_secret")
    op.drop_column("users", "totp_pending_secret")
