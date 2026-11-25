"""Indexes for the call reconciler and the global analysis admission query."""

from alembic import op

revision = "0164_call_pipeline_indexes"
down_revision = "0163_call_metadata_help"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Admission scans the oldest queued llm row while a global advisory lock is held;
    # without this index the sort grows with the backlog and lengthens the lock.
    op.execute(
        "CREATE INDEX idx_jobs_kind_status_queue ON jobs (kind, status, queued_at) "
        "WHERE status IN ('queued','failed_retryable')"
    )
    # concurrency_slot_free counts running jobs per tenant and kind on every claim.
    op.execute("CREATE INDEX idx_jobs_tenant_kind_status ON jobs (tenant_id, kind, status)")
    # reconcile_stuck_calls selects calls by status older than a cutoff every 30 s.
    op.execute(
        "CREATE INDEX idx_calls_tenant_status_updated ON calls (tenant_id, status, updated_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_calls_tenant_status_updated")
    op.execute("DROP INDEX IF EXISTS idx_jobs_tenant_kind_status")
    op.execute("DROP INDEX IF EXISTS idx_jobs_kind_status_queue")
