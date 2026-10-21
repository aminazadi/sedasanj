"""Add durable retry policy and attempt state to scheduled reports.

Revision ID: 0052_scheduled_report_retries
Revises: 0051_annual_plan_monthly_quotas
"""

from alembic import op

revision = "0052_scheduled_report_retries"
down_revision = "0051_annual_plan_monthly_quotas"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE scheduled_reports ADD COLUMN max_retries integer NOT NULL DEFAULT 3")
    op.execute("ALTER TABLE scheduled_reports ADD COLUMN retry_base_minutes integer NOT NULL DEFAULT 5")
    op.execute("ALTER TABLE scheduled_reports ADD CONSTRAINT scheduled_reports_retry_policy_check CHECK (max_retries BETWEEN 0 AND 3 AND retry_base_minutes BETWEEN 1 AND 60)")
    op.execute("ALTER TABLE scheduled_report_runs ADD COLUMN attempt_count integer NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE scheduled_report_runs ADD COLUMN max_retries integer NOT NULL DEFAULT 3")
    op.execute("ALTER TABLE scheduled_report_runs ADD COLUMN retry_base_minutes integer NOT NULL DEFAULT 5")
    op.execute("ALTER TABLE scheduled_report_runs ADD COLUMN next_attempt_at timestamptz")
    op.execute("ALTER TABLE scheduled_report_runs ADD CONSTRAINT scheduled_report_runs_retry_policy_check CHECK (attempt_count >= 0 AND max_retries BETWEEN 0 AND 3 AND retry_base_minutes BETWEEN 1 AND 60)")


def downgrade() -> None:
    op.execute("ALTER TABLE scheduled_report_runs DROP CONSTRAINT scheduled_report_runs_retry_policy_check")
    op.execute("ALTER TABLE scheduled_report_runs DROP COLUMN next_attempt_at")
    op.execute("ALTER TABLE scheduled_report_runs DROP COLUMN retry_base_minutes")
    op.execute("ALTER TABLE scheduled_report_runs DROP COLUMN max_retries")
    op.execute("ALTER TABLE scheduled_report_runs DROP COLUMN attempt_count")
    op.execute("ALTER TABLE scheduled_reports DROP CONSTRAINT scheduled_reports_retry_policy_check")
    op.execute("ALTER TABLE scheduled_reports DROP COLUMN retry_base_minutes")
    op.execute("ALTER TABLE scheduled_reports DROP COLUMN max_retries")
