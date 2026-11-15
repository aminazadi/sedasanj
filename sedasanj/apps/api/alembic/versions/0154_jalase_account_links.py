"""Link a personal Jalase-Negar account to a SedaSanj organization, and hide menu entries.

`jalase_account_links` (control) records which organization key a personal account holds, so the
link can be listed and revoked and the admin can filter linked users.  `jalase_menu_hidden`
(tenant, RLS) lets an organization admin hide a document category from the panel menu.
"""

from alembic import op

revision = "0154_jalase_account_links"
down_revision = "0153_jalase_gamification_help"
branch_labels = None
depends_on = None

POLICY = """USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
            OR current_setting('app.staff', true) = 'on')
        WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
            OR current_setting('app.staff', true) = 'on')"""


def upgrade() -> None:
    op.execute("""CREATE TABLE jalase_account_links (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        personal_tenant_id uuid NOT NULL REFERENCES tenants(id),
        personal_user_id uuid NOT NULL REFERENCES users(id),
        org_tenant_id uuid NOT NULL REFERENCES tenants(id),
        org_user_id uuid NOT NULL REFERENCES users(id),
        org_api_key_id uuid NOT NULL REFERENCES api_keys(id),
        status varchar(12) NOT NULL DEFAULT 'active' CHECK (status IN ('active','revoked')),
        linked_at timestamptz NOT NULL DEFAULT now(),
        revoked_at timestamptz)""")
    op.execute(
        "CREATE UNIQUE INDEX jalase_links_active_key ON jalase_account_links "
        "(personal_tenant_id, org_tenant_id) WHERE status = 'active'"
    )
    op.execute("CREATE INDEX jalase_links_org ON jalase_account_links (org_tenant_id)")
    op.execute("""CREATE TABLE jalase_menu_hidden (
        tenant_id uuid NOT NULL REFERENCES tenants(id),
        output_type_code varchar(40) NOT NULL,
        PRIMARY KEY (tenant_id, output_type_code))""")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON jalase_account_links TO cbi_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON jalase_menu_hidden TO cbi_app")
    op.execute("ALTER TABLE jalase_menu_hidden ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE jalase_menu_hidden FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY jalase_menu_hidden_tenant_isolation ON jalase_menu_hidden {POLICY}")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS jalase_menu_hidden")
    op.execute("DROP TABLE IF EXISTS jalase_account_links")
