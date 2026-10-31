"""Trigram indexes so the calls search box avoids sequential scans on substring matches."""

from alembic import op

revision = "0070_calls_search_trgm_indexes"
down_revision = "0069_billing_help_content"
branch_labels = None
depends_on = None

INDEXES = [
    ("idx_calls_dialed_trgm", "calls", "dialed_number"),
    ("idx_call_insights_summary_trgm", "call_insights", "summary"),
    ("idx_contacts_name_trgm", "contacts", "name"),
    ("idx_contacts_company_trgm", "contacts", "company"),
]


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    for name, table, column in INDEXES:
        op.execute(
            f"CREATE INDEX IF NOT EXISTS {name} ON {table} USING GIN ({column} gin_trgm_ops)"
        )


def downgrade() -> None:
    for name, _table, _column in reversed(INDEXES):
        op.execute(f"DROP INDEX IF EXISTS {name}")
