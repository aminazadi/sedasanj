"""Let transcript chunk embeddings use any model dimension.

Revision ID: 0058_transcript_chunks_any_dimension
Revises: 0057_contacts
"""

from alembic import op

revision = "0058_transcript_chunks_any_dimension"
down_revision = "0057_contacts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE transcript_chunks ALTER COLUMN embedding TYPE vector")


def downgrade() -> None:
    op.execute(
        "UPDATE transcript_chunks SET embedding = NULL, vector_status = 'pending', "
        "next_retry_at = NULL, error_detail = NULL "
        "WHERE embedding IS NOT NULL AND vector_dims(embedding) <> 384"
    )
    op.execute("ALTER TABLE transcript_chunks ALTER COLUMN embedding TYPE vector(384)")
