"""add per-key archive settings

Revision ID: 0012
Revises: 0011
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE api_keys ADD COLUMN archive_format text NOT NULL DEFAULT 'wav' "
        "CONSTRAINT api_keys_archive_format_check CHECK (archive_format IN ('wav','gzip','zip'))"
    )
    op.execute("ALTER TABLE api_keys ADD COLUMN archive_password_hash text")


def downgrade() -> None:
    op.execute("ALTER TABLE api_keys DROP COLUMN archive_password_hash")
    op.execute("ALTER TABLE api_keys DROP COLUMN archive_format")
