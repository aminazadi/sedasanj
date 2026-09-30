"""Integrity hardening: delivery cascade, call state check, job/reservation uniqueness.

Revision ID: 0002_integrity_hardening
Revises: 0001
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

revision = "0002_integrity_hardening"
down_revision = "0001"
branch_labels = None
depends_on = None

CALL_STATUSES = (
    "received",
    "reserved",
    "stored",
    "transcribing",
    "transcribed",
    "analyzing",
    "analyzed",
    "billed",
    "notified",
    "complete",
    "failed_retryable",
    "failed_terminal",
    "canceled",
)

UPGRADE = f"""
ALTER TABLE webhook_deliveries
  DROP CONSTRAINT webhook_deliveries_webhook_id_fkey,
  ADD CONSTRAINT webhook_deliveries_webhook_id_fkey
    FOREIGN KEY (webhook_id) REFERENCES webhooks(id) ON DELETE CASCADE;

ALTER TABLE webhook_deliveries
  ADD CONSTRAINT webhook_deliveries_call_id_fkey
    FOREIGN KEY (call_id) REFERENCES calls(id) ON DELETE SET NULL;

ALTER TABLE calls
  ADD CONSTRAINT calls_status_check CHECK (status IN ({",".join(f"'{s}'" for s in CALL_STATUSES)}));

-- One live reservation per call: settle/release must not race a second row (§10).
CREATE UNIQUE INDEX credit_reservations_held_per_call
  ON credit_reservations (call_id) WHERE status = 'held';

-- One in-flight job per (call, kind) so a duplicate queue entry cannot double-charge (§6).
CREATE UNIQUE INDEX jobs_active_per_call_kind
  ON jobs (call_id, kind) WHERE status IN ('queued', 'running');

CREATE INDEX idx_webhook_deliveries_tenant_created
  ON webhook_deliveries (tenant_id, created_at DESC);
"""

DOWNGRADE = """
DROP INDEX IF EXISTS idx_webhook_deliveries_tenant_created;
DROP INDEX IF EXISTS jobs_active_per_call_kind;
DROP INDEX IF EXISTS credit_reservations_held_per_call;
ALTER TABLE calls DROP CONSTRAINT IF EXISTS calls_status_check;
ALTER TABLE webhook_deliveries DROP CONSTRAINT IF EXISTS webhook_deliveries_call_id_fkey;
ALTER TABLE webhook_deliveries
  DROP CONSTRAINT webhook_deliveries_webhook_id_fkey,
  ADD CONSTRAINT webhook_deliveries_webhook_id_fkey
    FOREIGN KEY (webhook_id) REFERENCES webhooks(id);
"""


def upgrade() -> None:
    _exec(UPGRADE)


def downgrade() -> None:
    _exec(DOWNGRADE)
