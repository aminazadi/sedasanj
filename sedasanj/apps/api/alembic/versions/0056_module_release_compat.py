"""Add upper FreePBX bound and minimum PHP version to module releases."""

from alembic import op

revision = "0056_module_release_compat"
down_revision = "0055_module_diagnostics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE module_releases ADD COLUMN max_freepbx_major INTEGER")
    op.execute("ALTER TABLE module_releases ADD COLUMN min_php_version VARCHAR(16)")


def downgrade() -> None:
    op.execute("ALTER TABLE module_releases DROP COLUMN min_php_version")
    op.execute("ALTER TABLE module_releases DROP COLUMN max_freepbx_major")
