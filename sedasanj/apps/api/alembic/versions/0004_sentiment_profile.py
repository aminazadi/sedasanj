"""Per-channel text/voice sentiment profile on call insights.

Revision ID: 0004_sentiment_profile
Revises: 0003_call_progress
"""

from __future__ import annotations

from sqlalchemy import text

from alembic import op


def _exec(sql: str) -> None:
    """asyncpg rejects multi-statement prepared queries; run each command alone."""
    bind = op.get_bind()
    for part in sql.split(";"):
        statement = part.strip()
        if statement:
            bind.execute(text(statement))


revision = "0004_sentiment_profile"
down_revision = "0003_call_progress"
branch_labels = None
depends_on = None

UPGRADE = """
ALTER TABLE call_insights
  ADD COLUMN IF NOT EXISTS sentiment_profile jsonb;

CREATE INDEX IF NOT EXISTS idx_insights_sentiment_profile
  ON call_insights USING gin (sentiment_profile);
"""

DOWNGRADE = """
DROP INDEX IF EXISTS idx_insights_sentiment_profile;
ALTER TABLE call_insights DROP COLUMN IF EXISTS sentiment_profile;
"""


def upgrade() -> None:
    _exec(UPGRADE)


def downgrade() -> None:
    _exec(DOWNGRADE)
