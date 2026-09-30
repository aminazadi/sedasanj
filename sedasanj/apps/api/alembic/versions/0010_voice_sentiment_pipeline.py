"""Add the durable emotion2vec voice-sentiment stage.

Revision ID: 0010_voice_sentiment_pipeline
Revises: 0009_manual_transcript_correction
"""

from __future__ import annotations

from alembic import op

revision = "0010_voice_sentiment_pipeline"
down_revision = "0009_manual_transcript_correction"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE jobs DROP CONSTRAINT IF EXISTS jobs_kind_check")
    op.execute(
        "ALTER TABLE jobs ADD CONSTRAINT jobs_kind_check "
        "CHECK (kind IN ('asr','emotion','llm','notify'))"
    )
    op.execute(
        "ALTER TABLE processing_events DROP CONSTRAINT IF EXISTS processing_events_kind_check"
    )
    op.execute(
        "ALTER TABLE processing_events ADD CONSTRAINT processing_events_kind_check "
        "CHECK (kind IN ('pipeline','asr','emotion','llm','notify'))"
    )
    op.execute("ALTER TABLE calls DROP CONSTRAINT IF EXISTS calls_status_check")
    op.execute(
        "ALTER TABLE calls ADD CONSTRAINT calls_status_check CHECK (status IN ("
        "'received','reserved','stored','transcribing','transcribed',"
        "'emotion_queued','emotion_analyzing','analyzing','analyzed','billed',"
        "'notified','complete','failed_retryable','failed_terminal','canceled'))"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE calls SET status = 'transcribed' "
        "WHERE status IN ('emotion_queued','emotion_analyzing')"
    )
    op.execute(
        "DELETE FROM job_outbox WHERE job_id IN (SELECT id FROM jobs WHERE kind = 'emotion')"
    )
    op.execute("DELETE FROM processing_events WHERE kind = 'emotion'")
    op.execute("DELETE FROM jobs WHERE kind = 'emotion'")
    op.execute("ALTER TABLE calls DROP CONSTRAINT IF EXISTS calls_status_check")
    op.execute(
        "ALTER TABLE calls ADD CONSTRAINT calls_status_check CHECK (status IN ("
        "'received','reserved','stored','transcribing','transcribed','analyzing',"
        "'analyzed','billed','notified','complete','failed_retryable',"
        "'failed_terminal','canceled'))"
    )
    op.execute(
        "ALTER TABLE processing_events DROP CONSTRAINT IF EXISTS processing_events_kind_check"
    )
    op.execute(
        "ALTER TABLE processing_events ADD CONSTRAINT processing_events_kind_check "
        "CHECK (kind IN ('pipeline','asr','llm','notify'))"
    )
    op.execute("ALTER TABLE jobs DROP CONSTRAINT IF EXISTS jobs_kind_check")
    op.execute(
        "ALTER TABLE jobs ADD CONSTRAINT jobs_kind_check CHECK (kind IN ('asr','llm','notify'))"
    )
