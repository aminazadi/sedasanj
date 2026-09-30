"""Merge api_key archives and operator/follow-up heads.

Revision ID: 0014_merge_heads
Revises: 0012, 0013_follow_up_tasks
"""

from collections.abc import Sequence

revision: str = "0014_merge_heads"
down_revision: tuple[str, str] = ("0012", "0013_follow_up_tasks")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
