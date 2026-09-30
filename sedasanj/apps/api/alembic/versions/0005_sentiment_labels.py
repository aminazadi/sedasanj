"""Five-point sentiment labels: angry, sad, neutral, satisfied, happy.

Revision ID: 0005_sentiment_labels
Revises: 0004_sentiment_profile
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


revision = "0005_sentiment_labels"
down_revision = "0004_sentiment_profile"
branch_labels = None
depends_on = None

UPGRADE = """
ALTER TABLE call_insights DROP CONSTRAINT IF EXISTS call_insights_sentiment_check;

UPDATE call_insights SET sentiment = 'happy' WHERE sentiment = 'positive';
UPDATE call_insights SET sentiment = 'sad' WHERE sentiment = 'negative';

ALTER TABLE call_insights
  ADD CONSTRAINT call_insights_sentiment_check
    CHECK (sentiment IS NULL OR sentiment IN ('angry','sad','neutral','satisfied','happy'));
"""

DOWNGRADE = """
ALTER TABLE call_insights DROP CONSTRAINT IF EXISTS call_insights_sentiment_check;

UPDATE call_insights SET sentiment = 'positive' WHERE sentiment IN ('happy','satisfied');
UPDATE call_insights SET sentiment = 'negative' WHERE sentiment IN ('sad','angry');

ALTER TABLE call_insights
  ADD CONSTRAINT call_insights_sentiment_check
    CHECK (sentiment IS NULL OR sentiment IN ('positive','negative','neutral'));
"""


def upgrade() -> None:
    _exec(UPGRADE)


def downgrade() -> None:
    _exec(DOWNGRADE)
