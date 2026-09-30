"""Add database-per-tenant control-plane records.

Revision ID: 0020_tenant_database_control_plane
Revises: 0019_admin_commerce_control
"""

from alembic import op

revision = "0020_tenant_database_control_plane"
down_revision = "0019_admin_commerce_control"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE tenants DROP CONSTRAINT IF EXISTS tenants_status_check")
    op.execute(
        "ALTER TABLE tenants ADD CONSTRAINT tenants_status_check "
        "CHECK (status IN ('pending','provisioning','active','maintenance_readonly',"
        "'migration_failed','suspended','deleted'))"
    )
    op.execute("""
        CREATE TABLE tenant_database_registry (
            tenant_id uuid PRIMARY KEY REFERENCES tenants(id) ON DELETE CASCADE,
            database_name varchar(63) NOT NULL UNIQUE,
            runtime_role varchar(63) NOT NULL UNIQUE,
            encrypted_dsn text NOT NULL,
            status varchar(32) NOT NULL,
            schema_revision varchar(128),
            graph_name varchar(63) NOT NULL DEFAULT 'tenant_graph',
            last_health_at timestamptz,
            activated_at timestamptz,
            quarantine_until timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT tenant_database_registry_status_check
              CHECK (status IN ('provisioning','ready','maintenance','quarantined','failed'))
        )
    """)
    op.execute("""
        CREATE TABLE tenant_provisioning_jobs (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            status varchar(32) NOT NULL DEFAULT 'pending',
            step varchar(64) NOT NULL DEFAULT 'pending',
            attempt integer NOT NULL DEFAULT 0,
            error_detail text,
            started_at timestamptz,
            completed_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT tenant_provisioning_jobs_status_check
              CHECK (status IN ('pending','running','retryable','failed','succeeded'))
        )
    """)
    op.execute("""
        CREATE INDEX idx_tenant_provisioning_claim
          ON tenant_provisioning_jobs(status, created_at)
    """)
    op.execute("""
        CREATE TABLE tenant_data_migrations (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE UNIQUE,
            status varchar(32) NOT NULL DEFAULT 'pending',
            phase varchar(64) NOT NULL DEFAULT 'prechecking',
            manifest jsonb NOT NULL DEFAULT '{}',
            checkpoint jsonb NOT NULL DEFAULT '{}',
            error_detail text,
            source_locked_at timestamptz,
            cutover_at timestamptz,
            rollback_until timestamptz,
            completed_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE INDEX idx_tenant_data_migrations_status
          ON tenant_data_migrations(status, created_at)
    """)
    op.execute("""
        CREATE TABLE call_operator_assignments (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenants(id),
            call_id uuid NOT NULL REFERENCES calls(id) ON DELETE CASCADE,
            operator_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            agent_extension text NOT NULL,
            assignment_source text NOT NULL,
            confidence real NOT NULL DEFAULT 1,
            assigned_at timestamptz NOT NULL DEFAULT now(),
            superseded_at timestamptz
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX idx_call_operator_assignment_active
          ON call_operator_assignments(tenant_id, operator_id, call_id)
          WHERE superseded_at IS NULL
    """)
    op.execute("""
        INSERT INTO call_operator_assignments(
          tenant_id, call_id, operator_id, agent_extension, assignment_source, confidence
        )
        SELECT c.tenant_id, c.id, u.id, c.agent_extension, 'migration_exact_extension', 1
        FROM calls c
        JOIN users u ON u.tenant_id = c.tenant_id AND u.role = 'operator'
          AND btrim(u.extension) = btrim(c.agent_extension)
        WHERE c.agent_extension IS NOT NULL AND btrim(c.agent_extension) <> ''
        ON CONFLICT DO NOTHING
    """)
    op.execute("ALTER TABLE call_operator_assignments ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE call_operator_assignments FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY call_operator_assignments_tenant_isolation
          ON call_operator_assignments
          USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
            OR current_setting('app.staff', true) = 'on')
          WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
            OR current_setting('app.staff', true) = 'on')
    """)
    op.execute("""
        REVOKE ALL ON tenant_database_registry, tenant_provisioning_jobs,
          tenant_data_migrations FROM PUBLIC
    """)
    op.execute("""
        GRANT SELECT, INSERT, UPDATE, DELETE ON tenant_database_registry,
          tenant_provisioning_jobs, tenant_data_migrations, call_operator_assignments TO cbi_app
    """)


def downgrade() -> None:
    op.execute(
        "DROP TABLE IF EXISTS call_operator_assignments, tenant_data_migrations, "
        "tenant_provisioning_jobs, tenant_database_registry CASCADE"
    )
    op.execute("ALTER TABLE tenants DROP CONSTRAINT IF EXISTS tenants_status_check")
    op.execute(
        "ALTER TABLE tenants ADD CONSTRAINT tenants_status_check "
        "CHECK (status IN ('active','suspended','deleted'))"
    )
