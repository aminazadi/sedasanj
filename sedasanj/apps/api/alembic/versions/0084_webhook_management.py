"""Webhook management: rotation, auto-disable and a readable delivery log.

Revision ID: 0084_webhook_management
Revises: 0083_integration_api_help_content
"""

from __future__ import annotations

from alembic import op

revision = "0084_webhook_management"
down_revision = "0083_integration_api_help_content"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE webhooks ADD COLUMN description text")
    op.execute("ALTER TABLE webhooks ADD COLUMN secret_previous text")
    op.execute("ALTER TABLE webhooks ADD COLUMN secret_rotated_at timestamptz")
    op.execute("ALTER TABLE webhooks ADD COLUMN consecutive_failures integer NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE webhooks ADD COLUMN disabled_at timestamptz")
    op.execute("ALTER TABLE webhooks ADD COLUMN disabled_reason text")
    op.execute("ALTER TABLE webhooks ADD COLUMN created_at timestamptz NOT NULL DEFAULT now()")
    op.execute("ALTER TABLE webhook_deliveries ADD COLUMN delivery_id uuid")
    op.execute("ALTER TABLE webhook_deliveries ADD COLUMN error text")
    op.execute("ALTER TABLE webhook_deliveries ADD COLUMN latency_ms integer")
    op.execute(
        "CREATE INDEX idx_webhook_deliveries_hook_created "
        "ON webhook_deliveries (webhook_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX idx_webhook_deliveries_replay "
        "ON webhook_deliveries (webhook_id, call_id, event) WHERE status_code BETWEEN 200 AND 299"
    )


def downgrade() -> None:
    op.execute("DROP INDEX idx_webhook_deliveries_replay")
    op.execute("DROP INDEX idx_webhook_deliveries_hook_created")
    op.execute("ALTER TABLE webhook_deliveries DROP COLUMN latency_ms")
    op.execute("ALTER TABLE webhook_deliveries DROP COLUMN error")
    op.execute("ALTER TABLE webhook_deliveries DROP COLUMN delivery_id")
    op.execute("ALTER TABLE webhooks DROP COLUMN created_at")
    op.execute("ALTER TABLE webhooks DROP COLUMN disabled_reason")
    op.execute("ALTER TABLE webhooks DROP COLUMN disabled_at")
    op.execute("ALTER TABLE webhooks DROP COLUMN consecutive_failures")
    op.execute("ALTER TABLE webhooks DROP COLUMN secret_rotated_at")
    op.execute("ALTER TABLE webhooks DROP COLUMN secret_previous")
    op.execute("ALTER TABLE webhooks DROP COLUMN description")
