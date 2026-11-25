"""Each Jalase-Negar output type has a menu icon chosen by the admin."""

from alembic import op

revision = "0160_jalase_output_type_icon"
down_revision = "0159_meetings_output_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE jalase_output_types ADD COLUMN icon varchar(40) NOT NULL DEFAULT 'sparkles'"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE jalase_output_types DROP COLUMN icon")
