"""Allow quick demo QR links to create a short-lived account login."""

from alembic import op

revision = "0049_quick_demo_qr_login"
down_revision = "0048_quick_demo"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE quick_demo_sessions ADD COLUMN auth_exchanged_at timestamptz")


def downgrade() -> None:
    op.execute("ALTER TABLE quick_demo_sessions DROP COLUMN auth_exchanged_at")
