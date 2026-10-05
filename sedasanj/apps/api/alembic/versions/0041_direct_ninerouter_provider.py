"""Add direct 9Router provider snapshots.

Revision ID: 0041_direct_ninerouter_provider
Revises: 0040_asr_transcript_revisions
"""

from alembic import op

revision = "0041_direct_ninerouter_provider"
down_revision = "0040_asr_transcript_revisions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("jobs", "analysis_runs", "transcript_revisions", "asr_transcript_revisions"):
        op.execute(
            f"ALTER TABLE {table} ADD COLUMN ai_provider text NOT NULL DEFAULT 'aiservice'"
        )
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT {table}_ai_provider_check "
            "CHECK (ai_provider IN ('aiservice','ninerouter_direct'))"
        )
    op.execute("ALTER TABLE jobs ADD COLUMN ai_model text")
    op.execute(
        "ALTER TABLE analysis_runs ADD COLUMN decision_provider text NOT NULL "
        "DEFAULT 'aiservice'"
    )
    op.execute("ALTER TABLE analysis_runs ADD COLUMN decision_model text NOT NULL DEFAULT ''")
    op.execute(
        "ALTER TABLE analysis_runs ADD CONSTRAINT analysis_runs_decision_provider_check "
        "CHECK (decision_provider IN ('aiservice','ninerouter_direct'))"
    )
    for table in ("call_knowledge", "transcript_chunks"):
        op.execute(
            f"ALTER TABLE {table} ADD COLUMN embedding_provider text NOT NULL DEFAULT 'aiservice'"
        )
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT {table}_embedding_provider_check "
            "CHECK (embedding_provider IN ('aiservice','ninerouter_direct'))"
        )


def downgrade() -> None:
    for table in ("transcript_chunks", "call_knowledge"):
        op.execute(f"ALTER TABLE {table} DROP COLUMN embedding_provider")
    op.execute("ALTER TABLE analysis_runs DROP COLUMN decision_model")
    op.execute("ALTER TABLE analysis_runs DROP COLUMN decision_provider")
    op.execute("ALTER TABLE jobs DROP COLUMN ai_model")
    for table in ("asr_transcript_revisions", "transcript_revisions", "analysis_runs", "jobs"):
        op.execute(f"ALTER TABLE {table} DROP COLUMN ai_provider")
