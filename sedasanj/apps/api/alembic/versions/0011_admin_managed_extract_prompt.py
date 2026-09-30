"""persist the exact prompt used for each analysis run

Revision ID: 0011
Revises: 0010
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010_voice_sentiment_pipeline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE analysis_runs ADD COLUMN system_prompt text")


def downgrade() -> None:
    op.execute("ALTER TABLE analysis_runs DROP COLUMN system_prompt")
