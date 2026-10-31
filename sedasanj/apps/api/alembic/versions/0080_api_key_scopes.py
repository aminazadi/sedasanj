"""API key scopes, expiry, source-address allowlist and last-used address.

Revision ID: 0080_api_key_scopes
Revises: 0077_assistant_knowledge_help_content
"""

from __future__ import annotations

from alembic import op

revision = "0080_api_key_scopes"
down_revision = "0077_assistant_knowledge_help_content"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing keys keep working: they receive every scope they could use before this change.
    op.execute(
        "ALTER TABLE api_keys ADD COLUMN scopes text[] NOT NULL "
        "DEFAULT ARRAY['ingest:write','crm:write','module:sync']"
    )
    op.execute("ALTER TABLE api_keys ALTER COLUMN scopes DROP DEFAULT")
    op.execute("ALTER TABLE api_keys ADD COLUMN expires_at timestamptz")
    op.execute("ALTER TABLE api_keys ADD COLUMN allowed_cidrs text[] NOT NULL DEFAULT '{}'")
    op.execute("ALTER TABLE api_keys ADD COLUMN last_used_ip inet")
    op.execute(
        "ALTER TABLE api_keys ADD CONSTRAINT api_keys_scopes_not_empty "
        "CHECK (cardinality(scopes) > 0)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE api_keys DROP CONSTRAINT api_keys_scopes_not_empty")
    op.execute("ALTER TABLE api_keys DROP COLUMN last_used_ip")
    op.execute("ALTER TABLE api_keys DROP COLUMN allowed_cidrs")
    op.execute("ALTER TABLE api_keys DROP COLUMN expires_at")
    op.execute("ALTER TABLE api_keys DROP COLUMN scopes")
