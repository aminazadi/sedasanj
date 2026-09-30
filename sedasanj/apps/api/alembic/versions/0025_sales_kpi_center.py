"""Add sales KPI center, teams, goals, and CRM outcomes.

Revision ID: 0025_sales_kpi_center
Revises: 0024_hybrid_knowledge
"""

# ruff: noqa: E501

from alembic import op

revision = "0025_sales_kpi_center"
down_revision = "0024_hybrid_knowledge"
branch_labels = None
depends_on = None


TABLES = (
    "sales_insights",
    "teams",
    "team_memberships",
    "kpi_configurations",
    "kpi_goals",
    "crm_outcomes",
)


def upgrade() -> None:
    statements = (
        "ALTER TABLE calls ADD COLUMN campaign_id text",
        "ALTER TABLE calls ADD COLUMN source text",
        "ALTER TABLE calls ADD COLUMN external_reference text",
        "CREATE INDEX idx_calls_tenant_campaign ON calls(tenant_id, campaign_id, started_at)",
        "CREATE INDEX idx_calls_tenant_external_reference ON calls(tenant_id, external_reference)",
        """
        CREATE TABLE sales_insights (
          call_id uuid PRIMARY KEY REFERENCES calls(id) ON DELETE CASCADE,
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          analysis_run_id uuid REFERENCES analysis_runs(id) ON DELETE SET NULL,
          taxonomy_version integer NOT NULL DEFAULT 1,
          funnel_stage text NOT NULL DEFAULT 'unknown',
          outcome text NOT NULL DEFAULT 'unknown',
          certainty text NOT NULL DEFAULT 'unknown',
          confidence real NOT NULL DEFAULT 0,
          product text,
          objections text[] NOT NULL DEFAULT '{}',
          win_loss_reason text,
          next_action text,
          next_action_due_at timestamptz,
          evidence jsonb NOT NULL DEFAULT '[]',
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT sales_insights_funnel_stage_check CHECK (funnel_stage IN ('all_calls','effective','qualified','interested','follow_up','proposal','won','lost','unknown')),
          CONSTRAINT sales_insights_outcome_check CHECK (outcome IN ('won','lost','follow_up','interested','not_qualified','unknown')),
          CONSTRAINT sales_insights_certainty_check CHECK (certainty IN ('explicit','probable','unknown')),
          CONSTRAINT sales_insights_confidence_check CHECK (confidence >= 0 AND confidence <= 1)
        )
        """,
        "CREATE INDEX idx_sales_insights_tenant_outcome ON sales_insights(tenant_id, outcome, certainty)",
        """
        CREATE TABLE teams (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL REFERENCES tenants(id),
          name text NOT NULL, active boolean NOT NULL DEFAULT true, created_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT teams_tenant_name_key UNIQUE(tenant_id, name)
        )
        """,
        """
        CREATE TABLE team_memberships (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL REFERENCES tenants(id),
          team_id uuid NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
          operator_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          valid_from timestamptz NOT NULL, valid_to timestamptz, created_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT team_memberships_window_check CHECK (valid_to IS NULL OR valid_to > valid_from)
        )
        """,
        "CREATE INDEX idx_team_memberships_operator_window ON team_memberships(tenant_id, operator_id, valid_from, valid_to)",
        "CREATE UNIQUE INDEX team_memberships_one_active_operator ON team_memberships(tenant_id, operator_id) WHERE valid_to IS NULL",
        """
        CREATE TABLE kpi_configurations (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL REFERENCES tenants(id),
          version integer NOT NULL, settings jsonb NOT NULL, active boolean NOT NULL DEFAULT true,
          created_by uuid REFERENCES users(id) ON DELETE SET NULL, created_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT kpi_configurations_tenant_version_key UNIQUE(tenant_id, version)
        )
        """,
        "CREATE INDEX idx_kpi_configurations_active ON kpi_configurations(tenant_id, active)",
        """
        CREATE TABLE kpi_goals (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL REFERENCES tenants(id),
          team_id uuid REFERENCES teams(id) ON DELETE CASCADE, metric text NOT NULL, target_value real NOT NULL,
          valid_from timestamptz NOT NULL, valid_to timestamptz NOT NULL,
          created_by uuid REFERENCES users(id) ON DELETE SET NULL, created_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT kpi_goals_window_check CHECK (valid_to > valid_from)
        )
        """,
        "CREATE INDEX idx_kpi_goals_scope_window ON kpi_goals(tenant_id, team_id, metric, valid_from, valid_to)",
        """
        CREATE TABLE crm_outcomes (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL REFERENCES tenants(id),
          external_lead_id text NOT NULL, call_id uuid REFERENCES calls(id) ON DELETE SET NULL,
          external_call_reference text, customer_id text, campaign_id text, source text, channel text,
          owner_reference text, funnel_stage text, outcome text NOT NULL, amount bigint, currency varchar(8),
          product text, occurred_at timestamptz NOT NULL, payload jsonb NOT NULL DEFAULT '{}',
          created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT crm_outcomes_tenant_lead_key UNIQUE(tenant_id, external_lead_id),
          CONSTRAINT crm_outcomes_outcome_check CHECK (outcome IN ('won','lost','follow_up','interested','not_qualified','unknown'))
        )
        """,
        "CREATE INDEX idx_crm_outcomes_tenant_time ON crm_outcomes(tenant_id, occurred_at)",
    )
    for statement in statements:
        op.execute(statement)

    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY {table}_tenant_isolation ON {table}
              USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid OR current_setting('app.staff', true) = 'on')
              WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid OR current_setting('app.staff', true) = 'on')
        """)
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO cbi_app")


def downgrade() -> None:
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    op.execute("DROP INDEX IF EXISTS idx_calls_tenant_external_reference")
    op.execute("DROP INDEX IF EXISTS idx_calls_tenant_campaign")
    op.execute("ALTER TABLE calls DROP COLUMN IF EXISTS external_reference")
    op.execute("ALTER TABLE calls DROP COLUMN IF EXISTS source")
    op.execute("ALTER TABLE calls DROP COLUMN IF EXISTS campaign_id")
