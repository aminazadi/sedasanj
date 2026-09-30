"""Per-call processing progress for the tenant panel.

Revision ID: 0003_call_progress
Revises: 0002_integrity_hardening
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


revision = "0003_call_progress"
down_revision = "0002_integrity_hardening"
branch_labels = None
depends_on = None

UPGRADE = """
ALTER TABLE calls
  ADD COLUMN progress_pct SMALLINT,
  ADD COLUMN progress_detail TEXT;

ALTER TABLE calls
  ADD CONSTRAINT calls_progress_pct_check
    CHECK (progress_pct IS NULL OR (progress_pct >= 0 AND progress_pct <= 100));
"""

DOWNGRADE = """
ALTER TABLE calls DROP CONSTRAINT IF EXISTS calls_progress_pct_check;
ALTER TABLE calls DROP COLUMN IF EXISTS progress_detail;
ALTER TABLE calls DROP COLUMN IF EXISTS progress_pct;
"""


def upgrade() -> None:
    _exec(UPGRADE)


def downgrade() -> None:
    _exec(DOWNGRADE)
