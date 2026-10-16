"""Add metadata-only missed calls.

Revision ID: 0045_missed_calls
Revises: 0044_assistant_socket_runs
"""

from alembic import op

revision = "0045_missed_calls"
down_revision = "0044_assistant_socket_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE calls ADD COLUMN call_type text NOT NULL DEFAULT 'answered'")
    op.execute("ALTER TABLE calls ADD CONSTRAINT calls_call_type_check CHECK (call_type IN ('answered','missed'))")
    op.execute("ALTER TABLE calls DROP CONSTRAINT IF EXISTS calls_status_check")
    op.execute("ALTER TABLE calls ADD CONSTRAINT calls_status_check CHECK (status IN ('received','reserved','stored','transcribing','transcribed','correcting','emotion_queued','emotion_analyzing','analyzing','analyzed','billed','notified','complete','failed_retryable','failed_terminal','canceled','missed'))")
    op.execute("CREATE INDEX idx_calls_tenant_type_started ON calls(tenant_id, call_type, started_at DESC)")


def downgrade() -> None:
    op.execute("DELETE FROM calls WHERE call_type = 'missed'")
    op.execute("DROP INDEX IF EXISTS idx_calls_tenant_type_started")
    op.execute("ALTER TABLE calls DROP CONSTRAINT IF EXISTS calls_status_check")
    op.execute("ALTER TABLE calls ADD CONSTRAINT calls_status_check CHECK (status IN ('received','reserved','stored','transcribing','transcribed','correcting','emotion_queued','emotion_analyzing','analyzing','analyzed','billed','notified','complete','failed_retryable','failed_terminal','canceled'))")
    op.execute("ALTER TABLE calls DROP CONSTRAINT IF EXISTS calls_call_type_check")
    op.execute("ALTER TABLE calls DROP COLUMN IF EXISTS call_type")
