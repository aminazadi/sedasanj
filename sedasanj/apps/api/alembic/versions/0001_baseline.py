"""baseline schema, indexes and row level security

Revision ID: 0001
Revises:
"""

from collections.abc import Sequence

from sqlalchemy import text

from alembic import op


def _exec(sql: str) -> None:
    """asyncpg rejects multi-statement prepared queries; run each command alone."""
    bind = op.get_bind()
    for part in sql.split(";"):
        statement = part.strip()
        if statement:
            bind.execute(text(statement))

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_TABLES: tuple[str, ...] = (
    "users",
    "api_keys",
    "audio_objects",
    "calls",
    "utterances",
    "transcripts",
    "analysis_runs",
    "call_insights",
    "jobs",
    "ledger_entries",
    "credit_reservations",
    "tenant_balance_cache",
    "webhooks",
    "webhook_deliveries",
)

SCHEMA = """
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS citext;

CREATE TABLE tenants (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name          text NOT NULL,
  status        text NOT NULL DEFAULT 'active'
                  CHECK (status IN ('active','suspended','deleted')),
  timezone      text NOT NULL DEFAULT 'Asia/Tehran',
  locale        text NOT NULL DEFAULT 'fa',
  price_per_minute_toman integer NOT NULL,
  monthly_minute_quota   integer,
  max_concurrent_jobs    integer NOT NULL DEFAULT 10,
  audio_retention_days   integer NOT NULL DEFAULT 30,
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE users (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     uuid NOT NULL REFERENCES tenants(id),
  email         citext NOT NULL,
  password_hash text NOT NULL,
  role          text NOT NULL CHECK (role IN ('org_admin','operator','viewer')),
  totp_secret   text,
  created_at    timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, email)
);

CREATE TABLE staff_users (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email         citext UNIQUE NOT NULL,
  password_hash text NOT NULL,
  role          text NOT NULL CHECK (role IN ('super_admin','support')),
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE refresh_tokens (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  token_hash    text NOT NULL,
  expires_at    timestamptz NOT NULL,
  revoked_at    timestamptz,
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE staff_refresh_tokens (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  staff_user_id uuid NOT NULL REFERENCES staff_users(id) ON DELETE CASCADE,
  token_hash    text NOT NULL,
  expires_at    timestamptz NOT NULL,
  revoked_at    timestamptz,
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE api_keys (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     uuid NOT NULL REFERENCES tenants(id),
  key_hash      text NOT NULL,
  key_prefix    text NOT NULL,
  label         text,
  last_used_at  timestamptz,
  revoked_at    timestamptz,
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE audio_objects (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     uuid NOT NULL REFERENCES tenants(id),
  bucket        text NOT NULL,
  object_key    text NOT NULL,
  sha256        text NOT NULL,
  bytes         bigint NOT NULL,
  sample_rate   integer NOT NULL,
  channels      smallint NOT NULL,
  duration_ms   integer NOT NULL,
  expires_at    timestamptz,
  deleted_at    timestamptz,
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE calls (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id          uuid NOT NULL REFERENCES tenants(id),
  audio_id           uuid REFERENCES audio_objects(id),
  asterisk_uniqueid  text NOT NULL,
  caller_number      text,
  dialed_number      text,
  direction          text,
  agent_extension    text,
  started_at         timestamptz NOT NULL,
  ended_at           timestamptz NOT NULL,
  duration_ms        integer NOT NULL,
  billed_seconds     integer,
  status             text NOT NULL,
  error_code         text,
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, asterisk_uniqueid)
);

CREATE TABLE utterances (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  call_id       uuid NOT NULL REFERENCES calls(id) ON DELETE CASCADE,
  tenant_id     uuid NOT NULL REFERENCES tenants(id),
  channel       smallint NOT NULL CHECK (channel IN (0,1)),
  t_start_ms    integer NOT NULL,
  t_end_ms      integer NOT NULL,
  text          text NOT NULL
);

CREATE TABLE transcripts (
  call_id       uuid PRIMARY KEY REFERENCES calls(id) ON DELETE CASCADE,
  tenant_id     uuid NOT NULL REFERENCES tenants(id),
  full_text     text NOT NULL,
  search        tsvector GENERATED ALWAYS AS
                  (to_tsvector('simple', full_text)) STORED,
  asr_model     text NOT NULL,
  asr_version   text NOT NULL,
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE analysis_runs (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  call_id        uuid NOT NULL REFERENCES calls(id) ON DELETE CASCADE,
  tenant_id      uuid NOT NULL REFERENCES tenants(id),
  llm_model      text NOT NULL,
  prompt_version text NOT NULL,
  raw_output     text,
  result         jsonb,
  status         text NOT NULL,
  created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE call_insights (
  call_id         uuid PRIMARY KEY REFERENCES calls(id) ON DELETE CASCADE,
  tenant_id       uuid NOT NULL REFERENCES tenants(id),
  summary         text,
  keywords        text[],
  sentiment       text CHECK (sentiment IN ('positive','negative','neutral')),
  sentiment_score real,
  intent          text,
  topics          text[],
  ner             jsonb,
  action_items    jsonb
);

CREATE TABLE jobs (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     uuid NOT NULL REFERENCES tenants(id),
  call_id       uuid NOT NULL REFERENCES calls(id) ON DELETE CASCADE,
  kind          text NOT NULL CHECK (kind IN ('asr','llm','notify')),
  status        text NOT NULL,
  attempt       integer NOT NULL DEFAULT 0,
  run_after     timestamptz NOT NULL DEFAULT now(),
  locked_at     timestamptz,
  error_code    text,
  error_detail  text,
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE ledger_entries (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id      uuid NOT NULL REFERENCES tenants(id),
  call_id        uuid REFERENCES calls(id),
  kind           text NOT NULL CHECK (kind IN
                   ('topup','reservation','settlement','release','adjustment')),
  seconds_delta  integer NOT NULL,
  toman_delta    integer NOT NULL,
  reservation_id uuid,
  idempotency_key text NOT NULL,
  created_at     timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, idempotency_key)
);

CREATE TABLE credit_reservations (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     uuid NOT NULL REFERENCES tenants(id),
  call_id       uuid NOT NULL REFERENCES calls(id),
  seconds       integer NOT NULL,
  toman         integer NOT NULL,
  status        text NOT NULL CHECK (status IN ('held','settled','released')),
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE tenant_balance_cache (
  tenant_id     uuid PRIMARY KEY REFERENCES tenants(id),
  seconds       integer NOT NULL,
  toman         integer NOT NULL,
  updated_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE packages (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name          text NOT NULL,
  minutes       integer NOT NULL,
  price_toman   integer NOT NULL,
  active        boolean NOT NULL DEFAULT true
);

CREATE TABLE webhooks (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     uuid NOT NULL REFERENCES tenants(id),
  url           text NOT NULL,
  secret        text NOT NULL,
  events        text[] NOT NULL,
  active        boolean NOT NULL DEFAULT true
);

CREATE TABLE webhook_deliveries (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  webhook_id    uuid NOT NULL REFERENCES webhooks(id),
  tenant_id     uuid REFERENCES tenants(id),
  call_id       uuid,
  event         text NOT NULL,
  payload       jsonb NOT NULL,
  attempt       integer NOT NULL,
  status_code   integer,
  next_retry_at timestamptz,
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE audit_events (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  actor_type    text NOT NULL,
  actor_id      uuid,
  tenant_id     uuid,
  action        text NOT NULL,
  payload       jsonb NOT NULL DEFAULT '{}',
  ip            inet,
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE platform_settings (
  key           varchar(64) PRIMARY KEY,
  value         text NOT NULL,
  updated_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_calls_tenant_started ON calls (tenant_id, started_at DESC);
CREATE INDEX idx_calls_tenant_status  ON calls (tenant_id, status);
CREATE INDEX idx_calls_caller_trgm    ON calls USING GIN (caller_number gin_trgm_ops);
CREATE INDEX idx_transcripts_search   ON transcripts USING GIN (search);
CREATE INDEX idx_insights_keywords    ON call_insights USING GIN (keywords);
CREATE INDEX idx_insights_ner         ON call_insights USING GIN (ner);
CREATE INDEX idx_utterances_call      ON utterances (call_id, t_start_ms);
CREATE INDEX idx_analysis_runs_call   ON analysis_runs (call_id, created_at DESC);
CREATE INDEX idx_ledger_tenant_created ON ledger_entries (tenant_id, created_at DESC);
CREATE INDEX idx_jobs_run             ON jobs (status, run_after)
  WHERE status IN ('queued','failed_retryable');
CREATE INDEX idx_audio_expiry         ON audio_objects (expires_at)
  WHERE expires_at IS NOT NULL;
"""

# Tenant isolation: policies read app.tenant_id, staff sessions set app.staff=on.
# FORCE ROW LEVEL SECURITY keeps the table owner subject to the policy as well.
RLS_TEMPLATE = """
ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
CREATE POLICY {table}_tenant_isolation ON {table}
  USING (
    tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
    OR current_setting('app.staff', true) = 'on'
  )
  WITH CHECK (
    tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
    OR current_setting('app.staff', true) = 'on'
  );
"""


def upgrade() -> None:
    _exec(SCHEMA)
    for table in TENANT_TABLES:
        _exec(RLS_TEMPLATE.format(table=table))


def downgrade() -> None:
    for table in reversed(TENANT_TABLES):
        _exec(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")
        _exec(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    _exec(
        """
        DROP TABLE IF EXISTS platform_settings, audit_events, webhook_deliveries, webhooks,
          packages, tenant_balance_cache, credit_reservations, ledger_entries, jobs,
          call_insights, analysis_runs, transcripts, utterances, calls, audio_objects,
          api_keys, staff_refresh_tokens, refresh_tokens, staff_users, users, tenants CASCADE
        """
    )
