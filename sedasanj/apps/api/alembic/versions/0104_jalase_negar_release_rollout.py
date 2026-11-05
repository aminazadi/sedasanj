"""Jalase-Negar releases: staged rollout, forced minimum version and release channel.

Also merges the two 0103 heads (account access help and speaker help content) into one.
"""

from alembic import op

revision = "0104_jalase_negar_release_rollout"
down_revision = ("0103_account_access_help", "0103_speaker_help_content")
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE jalase_negar_releases ADD COLUMN rollout_percent SMALLINT DEFAULT 100 NOT NULL"
    )
    op.execute(
        "ALTER TABLE jalase_negar_releases "
        "ADD COLUMN min_supported_version_code BIGINT DEFAULT 0 NOT NULL"
    )
    op.execute(
        "ALTER TABLE jalase_negar_releases ADD COLUMN channel VARCHAR(8) DEFAULT 'stable' NOT NULL"
    )
    op.execute(
        "ALTER TABLE jalase_negar_releases "
        "ADD CONSTRAINT jalase_negar_releases_rollout_check "
        "CHECK (rollout_percent BETWEEN 0 AND 100)"
    )
    op.execute(
        "ALTER TABLE jalase_negar_releases "
        "ADD CONSTRAINT jalase_negar_releases_channel_check "
        "CHECK (channel IN ('stable','beta'))"
    )
    op.execute(
        "ALTER TABLE jalase_negar_releases "
        "ADD CONSTRAINT jalase_negar_releases_min_supported_check "
        "CHECK (min_supported_version_code >= 0)"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE jalase_negar_releases "
        "DROP CONSTRAINT jalase_negar_releases_min_supported_check"
    )
    op.execute(
        "ALTER TABLE jalase_negar_releases DROP CONSTRAINT jalase_negar_releases_channel_check"
    )
    op.execute(
        "ALTER TABLE jalase_negar_releases DROP CONSTRAINT jalase_negar_releases_rollout_check"
    )
    op.execute("ALTER TABLE jalase_negar_releases DROP COLUMN channel")
    op.execute("ALTER TABLE jalase_negar_releases DROP COLUMN min_supported_version_code")
    op.execute("ALTER TABLE jalase_negar_releases DROP COLUMN rollout_percent")
