"""Store operator-requested transcript corrections separately from ASR text.

Revision ID: 0009_manual_transcript_correction
Revises: 0008_durable_pipeline
"""

from alembic import op

revision = "0009_manual_transcript_correction"
down_revision = "0008_durable_pipeline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE alembic_version "
        "ALTER COLUMN version_num TYPE varchar(255)"
    )
    op.execute("ALTER TABLE transcripts ADD COLUMN corrected_text text")
    op.execute("ALTER TABLE transcripts ADD COLUMN corrected_at timestamptz")


def downgrade() -> None:
    op.execute("ALTER TABLE transcripts DROP COLUMN IF EXISTS corrected_at")
    op.execute("ALTER TABLE transcripts DROP COLUMN IF EXISTS corrected_text")
