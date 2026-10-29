"""Add province and city to phonebook contacts."""

from alembic import op

revision = "0059_contact_geo"
down_revision = "0058_transcript_chunks_any_dimension"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE contacts ADD COLUMN province VARCHAR(60)")
    op.execute("ALTER TABLE contacts ADD COLUMN city VARCHAR(80)")
    op.execute(
        "ALTER TABLE contacts ADD CONSTRAINT contacts_city_province_check "
        "CHECK (city IS NULL OR province IS NOT NULL)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE contacts DROP CONSTRAINT contacts_city_province_check")
    op.execute("ALTER TABLE contacts DROP COLUMN city")
    op.execute("ALTER TABLE contacts DROP COLUMN province")
