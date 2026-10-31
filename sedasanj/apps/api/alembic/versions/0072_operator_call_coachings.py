"""Per-call AI operator coaching results with vector-searchable history.

Revision ID: 0072_operator_call_coachings
Revises: 0071_issabel_modules
"""

from __future__ import annotations

from alembic import op

revision = "0072_operator_call_coachings"
down_revision = "0071_issabel_modules"
branch_labels = None
depends_on = None

_TENANT_CHECK = (
    "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid "
    "OR current_setting('app.staff', true) = 'on'"
)


def upgrade() -> None:
    op.execute(
        "CREATE TABLE operator_call_coachings ("
        "id uuid PRIMARY KEY DEFAULT gen_random_uuid(), "
        "tenant_id uuid NOT NULL REFERENCES tenants(id), "
        "call_id uuid NOT NULL REFERENCES calls(id) ON DELETE CASCADE, "
        "analysis_run_id uuid REFERENCES analysis_runs(id) ON DELETE SET NULL, "
        "operator_id uuid REFERENCES users(id) ON DELETE SET NULL, "
        "operator_label text NOT NULL, "
        "provider text NOT NULL DEFAULT 'aiservice', "
        "model text NOT NULL DEFAULT '', "
        "prompt_hash text, "
        "status text NOT NULL DEFAULT 'queued' CHECK "
        "(status IN ('queued','running','succeeded','failed','skipped')), "
        "result jsonb, "
        "narrative text, "
        "embed_text text, "
        "embedding vector(384), "
        "embedding_model text, "
        "vector_status text NOT NULL DEFAULT 'pending', "
        "skip_reason text, "
        "error_code text, "
        "error_detail text, "
        "created_at timestamptz NOT NULL DEFAULT now(), "
        "completed_at timestamptz, "
        "UNIQUE (call_id, analysis_run_id))"
    )
    op.execute(
        "CREATE INDEX idx_operator_call_coachings_operator "
        "ON operator_call_coachings (tenant_id, operator_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX idx_operator_call_coachings_call "
        "ON operator_call_coachings (call_id, created_at DESC)"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON operator_call_coachings TO cbi_app")
    op.execute("ALTER TABLE operator_call_coachings ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE operator_call_coachings FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY operator_call_coachings_tenant_isolation ON operator_call_coachings "
        f"USING ({_TENANT_CHECK}) WITH CHECK ({_TENANT_CHECK})"
    )


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS operator_call_coachings_tenant_isolation ON operator_call_coachings"
    )
    op.execute("DROP TABLE IF EXISTS operator_call_coachings")
