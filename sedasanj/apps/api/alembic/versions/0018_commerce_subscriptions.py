"""Add plans, subscriptions, commerce, expiring credit, installations and leads.

Revision ID: 0018_commerce_subscriptions
Revises: 0017_call_assistant_and_operator_scores
"""

from sqlalchemy import text

from alembic import op

revision = "0018_commerce_subscriptions"
down_revision = "0017_call_assistant_and_operator_scores"
branch_labels = None
depends_on = None


def _exec(sql: str) -> None:
    bind = op.get_bind()
    for part in sql.split(";"):
        if part.strip():
            bind.execute(text(part))


def upgrade() -> None:
    bind = op.get_bind()
    duplicate_email = bind.execute(
        text(
            "SELECT lower(email::text) FROM users "
            "GROUP BY lower(email::text) HAVING count(*) > 1 LIMIT 1"
        )
    ).scalar_one_or_none()
    if duplicate_email is not None:
        raise RuntimeError(
            "duplicate user emails must be resolved before commerce migration"
        )
    _exec("""
    CREATE UNIQUE INDEX users_email_global_key ON users (lower(email::text));
    ALTER TABLE ledger_entries DROP CONSTRAINT ledger_entries_kind_check;
    ALTER TABLE ledger_entries ADD CONSTRAINT ledger_entries_kind_check CHECK (kind IN ('topup','reservation','settlement','release','adjustment','subscription_credit','credit_purchase','expiration','refund'));

    CREATE TABLE plans (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), code varchar(32) UNIQUE NOT NULL, name text NOT NULL, active boolean NOT NULL DEFAULT true, public boolean NOT NULL DEFAULT true, sort_order integer NOT NULL DEFAULT 0, created_at timestamptz NOT NULL DEFAULT now());
    CREATE TABLE plan_versions (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), plan_id uuid NOT NULL REFERENCES plans(id), version integer NOT NULL, monthly_price_toman integer NOT NULL, annual_price_toman integer, base_operators integer NOT NULL, intro_minutes integer NOT NULL, overage_price_per_minute_toman integer NOT NULL, assistant_tier varchar(32) NOT NULL, assistant_monthly_messages integer NOT NULL, assistant_source_limit integer NOT NULL, assistant_model text, allows_extra_operators boolean NOT NULL DEFAULT false, extra_operator_monthly_toman integer, extra_operator_annual_toman integer, trial_days integer, published_at timestamptz NOT NULL DEFAULT now(), UNIQUE(plan_id, version), CHECK(monthly_price_toman >= 0 AND base_operators >= 0 AND intro_minutes >= 0));
    CREATE TABLE subscriptions (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL REFERENCES tenants(id), plan_version_id uuid NOT NULL REFERENCES plan_versions(id), status varchar(32) NOT NULL CHECK(status IN ('pending_payment','trialing','active','expired','canceled')), billing_period varchar(16) NOT NULL CHECK(billing_period IN ('trial','monthly','annual','legacy')), period_start timestamptz NOT NULL, period_end timestamptz NOT NULL, cancel_at_period_end boolean NOT NULL DEFAULT false, next_plan_version_id uuid REFERENCES plan_versions(id), base_operators integer NOT NULL, extra_operators integer NOT NULL DEFAULT 0, price_per_minute_toman integer NOT NULL, assistant_tier varchar(32) NOT NULL, assistant_monthly_messages integer NOT NULL, assistant_source_limit integer NOT NULL, assistant_model text, intro_credit_issued_at timestamptz, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now());
    CREATE INDEX idx_subscriptions_tenant_status ON subscriptions(tenant_id, status, period_end);
    CREATE TABLE subscription_extras (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL REFERENCES tenants(id), subscription_id uuid NOT NULL REFERENCES subscriptions(id) ON DELETE CASCADE, kind varchar(32) NOT NULL, quantity integer NOT NULL, unit_price_toman integer NOT NULL, effective_at timestamptz NOT NULL, ends_at timestamptz);
    CREATE TABLE subscription_changes (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL REFERENCES tenants(id), subscription_id uuid NOT NULL REFERENCES subscriptions(id) ON DELETE CASCADE, kind varchar(32) NOT NULL, status varchar(24) NOT NULL, target_plan_version_id uuid REFERENCES plan_versions(id), requested_extra_operators integer, effective_at timestamptz NOT NULL, order_id uuid, created_at timestamptz NOT NULL DEFAULT now());
    CREATE TABLE orders (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL REFERENCES tenants(id), number varchar(32) UNIQUE NOT NULL, kind varchar(32) NOT NULL, status varchar(32) NOT NULL DEFAULT 'draft', amount_toman integer NOT NULL, callback_token varchar(64) UNIQUE NOT NULL, idempotency_key varchar(128) NOT NULL, customer_name text NOT NULL, customer_email citext NOT NULL, customer_mobile varchar(20) NOT NULL, invoice_profile jsonb NOT NULL DEFAULT '{}', terms_version varchar(32) NOT NULL DEFAULT '1', created_at timestamptz NOT NULL DEFAULT now(), paid_at timestamptz, UNIQUE(tenant_id, idempotency_key));
    CREATE TABLE order_items (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), order_id uuid NOT NULL REFERENCES orders(id) ON DELETE CASCADE, tenant_id uuid NOT NULL REFERENCES tenants(id), kind varchar(32) NOT NULL, description text NOT NULL, quantity integer NOT NULL, unit_price_toman integer NOT NULL, total_toman integer NOT NULL, metadata_json jsonb NOT NULL DEFAULT '{}');
    CREATE TABLE payment_attempts (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), order_id uuid NOT NULL REFERENCES orders(id), tenant_id uuid NOT NULL REFERENCES tenants(id), gateway varchar(32) NOT NULL, status varchar(32) NOT NULL, amount_rial bigint NOT NULL, authority varchar(64) UNIQUE, ref_id varchar(64), response_json jsonb NOT NULL DEFAULT '{}', created_at timestamptz NOT NULL DEFAULT now(), verified_at timestamptz);
    CREATE TABLE invoices (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), order_id uuid UNIQUE NOT NULL REFERENCES orders(id), tenant_id uuid NOT NULL REFERENCES tenants(id), number varchar(32) UNIQUE NOT NULL, amount_toman integer NOT NULL, profile_snapshot jsonb NOT NULL, issued_at timestamptz NOT NULL DEFAULT now());
    CREATE TABLE credit_grants (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL REFERENCES tenants(id), source varchar(32) NOT NULL, source_id uuid, total_seconds integer NOT NULL, remaining_seconds integer NOT NULL, expires_at timestamptz, created_at timestamptz NOT NULL DEFAULT now());
    CREATE INDEX idx_credit_grants_available ON credit_grants(tenant_id, expires_at, created_at);
    CREATE TABLE reservation_allocations (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL REFERENCES tenants(id), reservation_id uuid NOT NULL REFERENCES credit_reservations(id) ON DELETE CASCADE, grant_id uuid NOT NULL REFERENCES credit_grants(id), seconds integer NOT NULL, UNIQUE(reservation_id, grant_id));
    CREATE TABLE assistant_usage (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL REFERENCES tenants(id), user_id uuid REFERENCES users(id) ON DELETE SET NULL, message_id uuid REFERENCES chat_messages(id) ON DELETE SET NULL, period_start timestamptz NOT NULL, status varchar(24) NOT NULL, model text, prompt_tokens integer, completion_tokens integer, created_at timestamptz NOT NULL DEFAULT now());
    CREATE INDEX idx_assistant_usage_period ON assistant_usage(tenant_id, period_start, status);
    CREATE TABLE installation_requests (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL REFERENCES tenants(id), order_id uuid REFERENCES orders(id), kind varchar(32) NOT NULL, status varchar(32) NOT NULL, pbx_type text NOT NULL, pbx_version text, extension_count integer NOT NULL, connection_method text NOT NULL, technical_contact text NOT NULL, preferred_time text, notes text, internal_notes text, scheduled_at timestamptz, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now());
    CREATE TABLE contact_leads (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), name text NOT NULL, organization text NOT NULL, mobile varchar(20) NOT NULL, email citext NOT NULL, message text NOT NULL, source varchar(64) NOT NULL DEFAULT 'contact_page', status varchar(24) NOT NULL DEFAULT 'new', owner_id uuid REFERENCES staff_users(id) ON DELETE SET NULL, created_at timestamptz NOT NULL DEFAULT now());
    CREATE TABLE signup_otps (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), mobile varchar(20) NOT NULL, email citext NOT NULL, code_hash text NOT NULL, attempts integer NOT NULL DEFAULT 0, expires_at timestamptz NOT NULL, verified_at timestamptz, created_at timestamptz NOT NULL DEFAULT now());
    CREATE INDEX idx_signup_otps_mobile_created ON signup_otps(mobile, created_at DESC);
    CREATE TABLE trial_claims (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL REFERENCES tenants(id), email citext UNIQUE NOT NULL, mobile varchar(20) UNIQUE NOT NULL, created_at timestamptz NOT NULL DEFAULT now());

    INSERT INTO plans(code,name,sort_order,public) VALUES ('demo','دمو',0,true),('bronze','برنزی',10,true),('silver','نقره‌ای',20,true),('gold','طلایی',30,true),('legacy_custom','سفارشی قدیمی',100,false);
    INSERT INTO plan_versions(plan_id,version,monthly_price_toman,annual_price_toman,base_operators,intro_minutes,overage_price_per_minute_toman,assistant_tier,assistant_monthly_messages,assistant_source_limit,allows_extra_operators,extra_operator_monthly_toman,extra_operator_annual_toman,trial_days)
      SELECT id,1,0,NULL,0,20,2000,'demo',10,3,false,NULL,NULL,7 FROM plans WHERE code='demo';
    INSERT INTO plan_versions(plan_id,version,monthly_price_toman,annual_price_toman,base_operators,intro_minutes,overage_price_per_minute_toman,assistant_tier,assistant_monthly_messages,assistant_source_limit) SELECT id,1,799000,7990000,2,100,2000,'simple',50,8 FROM plans WHERE code='bronze';
    INSERT INTO plan_versions(plan_id,version,monthly_price_toman,annual_price_toman,base_operators,intro_minutes,overage_price_per_minute_toman,assistant_tier,assistant_monthly_messages,assistant_source_limit) SELECT id,1,1799000,17990000,5,200,2000,'medium',200,20 FROM plans WHERE code='silver';
    INSERT INTO plan_versions(plan_id,version,monthly_price_toman,annual_price_toman,base_operators,intro_minutes,overage_price_per_minute_toman,assistant_tier,assistant_monthly_messages,assistant_source_limit,allows_extra_operators,extra_operator_monthly_toman,extra_operator_annual_toman) SELECT id,1,4999000,49990000,10,400,2000,'advanced',1000,50,true,199000,1990000 FROM plans WHERE code='gold';
    INSERT INTO plan_versions(plan_id,version,monthly_price_toman,annual_price_toman,base_operators,intro_minutes,overage_price_per_minute_toman,assistant_tier,assistant_monthly_messages,assistant_source_limit) SELECT id,1,0,NULL,2147483647,0,2000,'advanced',2147483647,50 FROM plans WHERE code='legacy_custom';
    INSERT INTO subscriptions(tenant_id,plan_version_id,status,billing_period,period_start,period_end,base_operators,extra_operators,price_per_minute_toman,assistant_tier,assistant_monthly_messages,assistant_source_limit)
      SELECT t.id,pv.id,'active','legacy',t.created_at,'9999-12-31T00:00:00Z',t.max_operators,0,t.price_per_minute_toman,'advanced',2147483647,50 FROM tenants t CROSS JOIN plan_versions pv INNER JOIN plans p ON p.id=pv.plan_id WHERE p.code='legacy_custom';
    INSERT INTO credit_grants(tenant_id,source,total_seconds,remaining_seconds) SELECT tenant_id,'legacy',seconds,seconds FROM tenant_balance_cache WHERE seconds > 0;
    UPDATE packages SET active=false;
    INSERT INTO packages(name,minutes,price_toman,active) VALUES ('۱۰۰ دقیقه',100,200000,true),('۵۰۰ دقیقه',500,1000000,true),('۱۰۰۰ دقیقه',1000,2000000,true);
    """)

    tenant_tables = ('subscriptions','subscription_extras','subscription_changes','orders','order_items','payment_attempts','invoices','credit_grants','reservation_allocations','assistant_usage','installation_requests','trial_claims')
    for table in tenant_tables:
        bind.execute(text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO cbi_app"))
        bind.execute(text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
        bind.execute(text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))
        bind.execute(text(f"CREATE POLICY {table}_tenant_isolation ON {table} USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid OR current_setting('app.staff', true) = 'on') WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid OR current_setting('app.staff', true) = 'on')"))
    _exec("GRANT SELECT ON plans, plan_versions TO cbi_app; GRANT SELECT, INSERT, UPDATE, DELETE ON contact_leads, signup_otps TO cbi_app")


def downgrade() -> None:
    _exec("""
    DROP TABLE IF EXISTS trial_claims, signup_otps, contact_leads, installation_requests, assistant_usage, reservation_allocations, credit_grants, invoices, payment_attempts, order_items, subscription_changes, subscription_extras, orders, subscriptions, plan_versions, plans CASCADE;
    DROP INDEX IF EXISTS users_email_global_key;
    DELETE FROM packages WHERE name IN ('۱۰۰ دقیقه','۵۰۰ دقیقه','۱۰۰۰ دقیقه');
    ALTER TABLE ledger_entries DROP CONSTRAINT IF EXISTS ledger_entries_kind_check;
    ALTER TABLE ledger_entries ADD CONSTRAINT ledger_entries_kind_check CHECK (kind IN ('topup','reservation','settlement','release','adjustment'));
    """)
