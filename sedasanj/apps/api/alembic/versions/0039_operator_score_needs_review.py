"""Allow incomplete operator evaluations to wait for review.

Revision ID: 0039_operator_score_needs_review
Revises: 0038_initialize_knowledge_graph_labels
"""

from alembic import op

revision = "0039_operator_score_needs_review"
down_revision = "0038_initialize_knowledge_graph_labels"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("operator_call_scores_status_check", "operator_call_scores", type_="check")
    op.create_check_constraint(
        "operator_call_scores_status_check",
        "operator_call_scores",
        "status IN ('queued', 'running', 'succeeded', 'failed', 'ineligible', 'needs_review')",
    )


def downgrade() -> None:
    op.execute("UPDATE operator_call_scores SET status = 'failed' WHERE status = 'needs_review'")
    op.drop_constraint("operator_call_scores_status_check", "operator_call_scores", type_="check")
    op.create_check_constraint(
        "operator_call_scores_status_check",
        "operator_call_scores",
        "status IN ('queued', 'running', 'succeeded', 'failed', 'ineligible')",
    )
