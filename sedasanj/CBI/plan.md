# Voice Analytics Platform — Technical Specification (v1)

post-call Persian voice analytics (ASR + LLM), multi-tenant SaaS

---

## 1. Product scope

### 1.1 v1 flow

A tenant installs `cbi-agent` next to Asterisk. After each call hangs up, the agent uploads a stereo WAV. The platform stores the audio, transcribes it (Shenava-Koochik), extracts structured insights (Dorna: summary, sentiment, intent, NER, action items, topics), debits credit from a ledger, shows results in a web panel, and optionally POSTs a webhook.

### 1.2 Out of scope for v1

- Live captions / real-time streaming
- Speaker diarization ML (dual-channel recording covers caller vs callee)
- Kubernetes, Elasticsearch, MongoDB, microservices
- Mobile apps
- Payment gateway (credit top-up is staff-applied)

---

## 2. Locked decisions

| Decision | Choice |
|---|---|
| Capture | MixMonitor stereo WAV, upload after hangup |
| Audio format | WAV, linear PCM only (no raw/slin/ulaw blobs, no MP3) |
| Database | PostgreSQL 16 (single DB; `jsonb` for LLM output, FTS + `pg_trgm` for search) |
| Queue | Redis 7 + ARQ |
| Object store | MinIO (S3 API) |
| Process model | 1 FastAPI modular monolith + ASR workers + LLM workers + notify worker |
| LLM serving | 2 × `llama-server` (shared GGUF, `--parallel 4`), never one model copy per worker |
| Long transcripts | Chunk → map summaries → reduce extract (§9.2) |
| Billing | Reserve at ingest, settle on success, release on terminal failure (§10) |
| Agent auth | `Authorization: Bearer sk_live_…` header |
| Reverse proxy | Nginx Proxy Manager بیرونی (TLS) |
| Frontend | React + TypeScript + Tailwind, RTL default |

Audio handling rules that follow from these:

- Accept 8 kHz or 16 kHz PCM WAV, 1–2 channels. Everything else → `415 unsupported_audio`.
- MinIO keeps the original upload. Resampling to 16 kHz happens only in worker scratch.
- Stereo layout: **left = caller, right = callee**. Mono is accepted; speaker labels are then omitted.

---

## 3. Runtime view

```
┌─────────────────────────────────────────────┐
│ Customer site                               │
│  Asterisk ──MixMonitor──► WAV (L=caller,    │
│                           R=callee)         │
│  cbi-agent: on Hangup → POST /v1/ingest     │
└──────────────────────┬──────────────────────┘
                       │ TLS, API key
                       ▼
┌─────────────────────────────────────────────┐
│ DL580 — docker compose                      │
│  Published ports → api + client/admin       │
│  api ─ PostgreSQL / MinIO / Redis           │
│      └─ q:asr → worker-asr (Shenava)        │
│              └─ q:llm → worker-llm          │
│                        └→ llama-server ×2   │
│              └─ q:notify → worker-notify    │
│  Prometheus + Grafana + Loki                │
└─────────────────────────────────────────────┘
```

One codebase, one OpenAPI spec, one database. ASR/LLM/notify are separate processes only because they pin CPU/RAM.

---

## 4. Asterisk agent (`cbi-agent`)

Python daemon on the customer PBX. Not an Asterisk module, never owns the channel.

Loop: connect AMI → on `Hangup`, locate recording in `monitor_dir` → merge two mono legs to stereo WAV if needed → `POST /v1/ingest/calls` → delete or retain per config → retry with exponential backoff on failure. Failed uploads stay on disk and retry on a timer, so PBX-side data survives platform downtime.

### 4.1 Dialplan (shipped snippet)

The call is bridged as usual; recording is a side effect. Never route the live channel into `Stasis()`.

```asterisk
[from-internal]
exten => _X.,1,NoOp(CBI record ${UNIQUEID})
 same => n,MixMonitor(${UNIQUEID}.wav,abr(${UNIQUEID}-in.wav)t(${UNIQUEID}-out.wav))
 same => n,Dial(PJSIP/${EXTEN},,Ttr)
 same => n,Hangup()
```

`r()` = received (caller) leg, `t()` = transmitted (callee) leg.

### 4.2 Config

```toml
# /etc/cbi-agent/cbi-agent.toml
[server]
base_url = "https://api.example.com"
timeout_seconds = 60

[auth]
api_key = "sk_live_..."

[asterisk]
ami_host = "127.0.0.1"
ami_port = 5038
ami_user = "cbi"
ami_secret = "..."
monitor_dir = "/var/spool/asterisk/monitor"

[audio]
sample_rate = 8000        # Asterisk native; server resamples for ASR
channels = 2
delete_after_upload = true

[retry]
max_attempts = 8
backoff_seconds = 2
```

### 4.3 Upload contract

`POST /v1/ingest/calls` — multipart/form-data

Headers: `Authorization: Bearer sk_live_…`, `Idempotency-Key: {asterisk_uniqueid}`

| Field | Type | Required |
|---|---|---|
| `file` | `audio/wav`, PCM, 1–2 ch, 8/16 kHz | yes |
| `asterisk_uniqueid` | string, unique per tenant | yes |
| `caller_number` | string | yes |
| `dialed_number` | string | yes |
| `started_at` | RFC3339 | yes |
| `ended_at` | RFC3339 | yes |
| `direction` | `inbound` \| `outbound` | no |
| `agent_extension` | string | no |

`201`:

```json
{ "call_id": "8f1c…", "status": "queued", "reservation_id": "b2aa…" }
```

Rules:

- Replay of the same `Idempotency-Key` → `200` with the original `call_id`.
- `ffprobe` validates before the MinIO put; non-PCM, >2 channels, or unexpected rate → `415 unsupported_audio`.
- Billable duration comes from the probed file, not client timestamps. If they disagree by >20%, log a warning and trust the file.

### 4.4 v2 placeholder — live stream

WebSocket ingest (`wss…/v1/ingest/stream`, framed PCM, auth in first frame). Not built until the post-call path is stable in production.

---

## 5. Call state machine

One `status` per call. Workers transition only via conditional `UPDATE … WHERE status = expected`.

```
received → reserved → stored → transcribing → transcribed
        → analyzing → analyzed → billed → notified → complete

any step → failed_retryable | failed_terminal | canceled
```

- `failed_retryable`: worker crash, LLM JSON parse failure, upstream 5xx
- `failed_terminal`: bad audio, retries exhausted, tenant suspended
- `canceled`: admin action

Retry policy (attempts tracked in `jobs`):

| Job | Max attempts | Backoff |
|---|---|---|
| asr | 5 | 5s × 2^n |
| llm | 4 | 10s × 2^n (includes one JSON repair) |
| notify | 8 | 15s × 2^n, then dead-letter |

---

## 6. Queues and job contracts

ARQ on Redis. Three queues; payloads are minimal — workers read everything else from the DB.

| Queue | Consumer | Payload |
|---|---|---|
| `q:asr` | worker-asr | `{"call_id": uuid}` |
| `q:llm` | worker-llm | `{"call_id": uuid, "analysis_run_id": uuid}` |
| `q:notify` | worker-notify | `{"call_id": uuid, "event": "call.complete" \| "call.failed" \| "balance.low"}` |

Worker contract (all three):

1. Claim: conditional status `UPDATE`; if 0 rows, another worker owns it — drop the job.
2. Work; write results in one transaction with the status transition.
3. On exception: increment `jobs.attempt`, set `run_after = now() + backoff`, requeue; past max attempts → `failed_terminal` (+ release reservation for asr/llm).

Enqueue happens in the same DB transaction as the status write (transactional outbox not needed at this scale; ARQ enqueue after commit with a reconciler cron that re-enqueues stuck rows older than 10 min).

---

## 7. Backend

### 7.1 Repo layout

```
apps/
  api/                  # FastAPI: auth, tenants, ingest, calls,
                        # billing, webhooks, admin, shared/
  worker_asr/
  worker_llm/           # HTTP client to llama-server
  worker_notify/
  agent/                # cbi-agent shipped to customers
web/
  client/               # tenant panel
  admin/                # staff panel
deploy/
  compose.yml
  nginx.frontend.conf
  prometheus/
```

Python 3.12, uv, SQLAlchemy 2 + Alembic, Pydantic v2, ARQ, httpx.

### 7.2 Tenant isolation

- Every JWT / API key resolves to `tenant_id`
- Postgres RLS on all tenant tables via `set_config('app.tenant_id', …)`
- Application queries also filter `tenant_id` (defense in depth)
- Staff role uses a separate DB role that bypasses RLS

### 7.3 Error model

```json
{
  "error": {
    "code": "insufficient_credit",
    "message": "Reservation requires 180 seconds; available 60",
    "retryable": false,
    "request_id": "…"
  }
}
```

Codes: `unauthorized`, `forbidden`, `insufficient_credit`, `tenant_suspended`, `conflict_idempotency`, `unsupported_audio`, `not_found`, `rate_limited`, `internal`.

### 7.4 Environment variables

| Var | Example | Used by |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://…` | api, workers |
| `REDIS_URL` | `redis://redis:6379/0` | api, workers |
| `MINIO_ENDPOINT` / `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` | | api, worker-asr |
| `MINIO_BUCKET_AUDIO` | `audio` | api, worker-asr |
| `JWT_SECRET` | 32+ chars | api |
| `API_KEY_PEPPER` | 32+ chars | api |
| `SHENAVA_MODEL_PATH` | `/models/shenava-koochik-int8.bin` | worker-asr |
| `LLAMA_SERVER_URLS` | `http://llm1:8081,http://llm2:8081` | worker-llm |
| `PROMPT_VERSION` | `extract-fa-v1` | worker-llm |
| `SMTP_URL` | | worker-notify |
| `PUBLIC_BASE_URL` | `https://api.example.com` | api |

Secrets via Docker secrets or env files outside git.

---

## 8. Data model

PostgreSQL 16. UUID PKs, `timestamptz` everywhere. Full DDL is the Alembic baseline migration; tables:

```sql
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
  password_hash text NOT NULL,                -- argon2id
  role          text NOT NULL CHECK (role IN ('org_admin','operator','viewer')),
  totp_secret   text,
  created_at    timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, email)
);

CREATE TABLE staff_users (                    -- platform operators, not tenant-scoped
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

CREATE TABLE api_keys (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     uuid NOT NULL REFERENCES tenants(id),
  key_hash      text NOT NULL,                -- sha256(secret + pepper)
  key_prefix    text NOT NULL,                -- sk_live_abcd
  label         text,
  last_used_at  timestamptz,
  revoked_at    timestamptz,
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE audio_objects (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     uuid NOT NULL REFERENCES tenants(id),
  bucket        text NOT NULL,
  object_key    text NOT NULL,                -- {tenant_id}/{call_id}.wav
  sha256        text NOT NULL,
  bytes         bigint NOT NULL,
  sample_rate   integer NOT NULL,
  channels      smallint NOT NULL,
  duration_ms   integer NOT NULL,
  expires_at    timestamptz,                  -- retention job target
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
  duration_ms        integer NOT NULL,        -- from probe
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
  channel       smallint NOT NULL CHECK (channel IN (0,1)), -- 0=caller,1=callee
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

CREATE TABLE call_insights (                  -- denormalized projection for list/filter
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
  seconds_delta  integer NOT NULL,            -- signed; reservations negative
  toman_delta    integer NOT NULL,            -- signed
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

CREATE TABLE tenant_balance_cache (           -- lock target for reserve; kept in sync
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
  secret        text NOT NULL,                -- HMAC key
  events        text[] NOT NULL,
  active        boolean NOT NULL DEFAULT true
);

CREATE TABLE webhook_deliveries (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  webhook_id    uuid NOT NULL REFERENCES webhooks(id),
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
  actor_type    text NOT NULL,                -- staff|user|system
  actor_id      uuid,
  tenant_id     uuid,
  action        text NOT NULL,
  payload       jsonb NOT NULL DEFAULT '{}',
  ip            inet,
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_calls_tenant_started ON calls (tenant_id, started_at DESC);
CREATE INDEX idx_calls_tenant_status  ON calls (tenant_id, status);
CREATE INDEX idx_transcripts_search   ON transcripts USING GIN (search);
CREATE INDEX idx_insights_keywords    ON call_insights USING GIN (keywords);
CREATE INDEX idx_insights_ner         ON call_insights USING GIN (ner);
CREATE INDEX idx_jobs_run             ON jobs (status, run_after)
  WHERE status IN ('queued','failed_retryable');
CREATE INDEX idx_audio_expiry         ON audio_objects (expires_at)
  WHERE expires_at IS NOT NULL;
```

Balance is the ledger sum; `tenant_balance_cache` is updated in the **same transaction** as every ledger insert and is the `FOR UPDATE` lock target for reservations.

---

## 9. Pipeline workers

### 9.1 ASR (worker-asr)

1. Download original WAV from MinIO to scratch
2. `ffmpeg` resample to 16 kHz s16le; split stereo into `left.wav` / `right.wav`
3. `AsrEngine.transcribe(path) -> list[Utterance]` (Shenava-Koochik via `tract`, fallback ONNX Runtime; `SHENAVA_MODEL_PATH`)
4. Write `utterances` per channel (whole-channel span if the engine gives no timestamps), build `transcripts.full_text`:

```
[caller 00:00] …
[agent  00:04] …
```

5. Status → `transcribed`, insert `analysis_runs` row, enqueue `q:llm`

Mono input: single pass, `channel=0`, no speaker labels.
Sizing: 4 workers (~300 MB each). 300 h/day ≈ 22.5 core-hours at RTF 0.075 — raise to 8 only if the ASR queue itself lags.

### 9.2 LLM (worker-llm + llama-server)

Serving: 2 × `llama-server`, round-robin from `LLAMA_SERVER_URLS`.

```
llama-server --model /models/dorna-llama3-8b-instruct-q4_k_m.gguf \
  --ctx-size 8192 --parallel 4 --threads 20 --host 0.0.0.0 --port 8081
```

RAM ≈ 12–20 GB per server (weights + KV for 4×8k slots). 8 total slots covers 300 h/day concentrated in a 10-hour business day (~6,000 three-minute calls × ~40 s decode). Scale `--parallel`/threads before adding a third copy.

Chunking — `T` = transcript tokens (≈ `len(chars)/2` for Persian):

| T | Strategy |
|---|---|
| < 3500 | Single extract prompt |
| 3500–12000 | 2500-token chunks, 200 overlap → summary per chunk → reduce extract |
| > 12000 | Same, extra reduce pass |

Never silently truncate.

Inference params: `temperature=0.2`, `response_format=json_object` where supported.

Output schema (Pydantic-validated; on failure one repair prompt, then `failed_retryable`):

```json
{
  "summary": "string",
  "keywords": ["string"],
  "sentiment": {
    "overall": "positive|negative|neutral",
    "score": 0.0,
    "phrases": [{"text": "string", "sentiment": "positive|negative|neutral"}]
  },
  "intent": "technical_support|sales_inquiry|complaint|consultation|billing|other",
  "ner": {
    "persons": [], "dates": [], "amounts": [],
    "phone_numbers": [], "organizations": []
  },
  "action_items": ["string"],
  "topics": ["string"]
}
```

Constraints: `keywords` ≤ 5, `topics` ≤ 3, `summary` 2–3 sentences, `score` ∈ [0,1].

System prompt `extract-fa-v1` (stored verbatim in repo at `apps/worker_llm/prompts/extract-fa-v1.txt`):

```
تو یک دستیار تحلیل مکالمات تلفنی فارسی هستی. متن پیاده‌شده‌ی مکالمه بین «caller» (مشتری) و «agent» (اپراتور) به تو داده می‌شود.
خروجی را فقط به صورت JSON معتبر مطابق اسکیمای داده‌شده تولید کن. هیچ متن اضافه، markdown یا توضیحی ننویس.
- summary: خلاصه ۲ تا ۳ جمله‌ای به فارسی
- keywords: حداکثر ۵ کلیدواژه فارسی
- sentiment.overall: احساس کلی مشتری
- intent: یکی از مقادیر مجاز اسکیما
- ner: اسامی افراد، تاریخ‌ها، مبالغ، شماره تلفن‌ها، نام سازمان‌ها (همان‌طور که در متن آمده)
- action_items: کارهای قابل پیگیری به فارسی
- topics: حداکثر ۳ موضوع
اگر موردی در مکالمه وجود ندارد، آرایه خالی یا null بگذار؛ چیزی از خودت نساز.
```

Any prompt change bumps `prompt_version`; old `analysis_runs` stay comparable.

On success: write `analysis_runs.result` + `call_insights`, status → `analyzed`, settle credit (§10), enqueue `q:notify`.

### 9.3 Notify (worker-notify)

- Webhook POST with `X-CBI-Signature: sha256={hmac(secret, "{ts}.{body}")}` and `X-CBI-Timestamp` (reject replays older than 5 min on receiver side)
- Email (SMTP) for `balance.low`
- Delivery log in `webhook_deliveries`; retries per §5, then dead-letter

Webhook payload:

```json
{
  "event": "call.complete",
  "timestamp": "2026-08-19T10:35:00Z",
  "tenant_id": "…",
  "call_id": "…",
  "data": {
    "caller_number": "0912…",
    "duration_ms": 245000,
    "summary": "…",
    "sentiment": "positive",
    "intent": "technical_support"
  }
}
```

Events: `call.complete`, `call.failed`, `balance.low`.

---

## 10. Billing

Billable seconds = `max(30, ceil(duration_ms / 1000))`, priced at `price_per_minute_toman / 60`.

**Reserve** (ingest, one transaction):

1. `SELECT … FOR UPDATE` on `tenant_balance_cache`
2. Insufficient → `402 insufficient_credit`, nothing stored
3. Insert `ledger_entries(kind=reservation)` + `credit_reservations(held)`, update cache
4. MinIO put, enqueue `q:asr`

**Settle** (on `analyzed`): settlement entry closes the hold at true cost, leftover released, reservation → `settled`.
**Release** (on `failed_terminal`): reversing entry, reservation → `released`, tenant not charged.

Idempotency keys: `reserve:{call_id}`, `settle:{call_id}`, `release:{call_id}` — enforced by the unique constraint.

Top-ups are staff-applied in v1 (`POST /v1/admin/tenants/{id}/topups` → `kind=topup`). `packages` exist for display; PSP integration later touches nothing but a new topup source.

---

## 11. HTTP API

JWT (humans) or API key (agent). All tenant routes require one.

**Auth**

| Method | Path | Notes |
|---|---|---|
| POST | `/v1/auth/login` | → access 15m + refresh 14d (rotated, hash stored) |
| POST | `/v1/auth/refresh` | |
| POST | `/v1/auth/logout` | revoke refresh |
| POST | `/v1/auth/api-keys` | org_admin; secret returned once |
| GET | `/v1/auth/api-keys` | prefix + last_used only |
| DELETE | `/v1/auth/api-keys/{id}` | revoke |

Access claims: `sub`, `tenant_id`, `role`, `typ=access`.

**Ingest**

| Method | Path | Notes |
|---|---|---|
| POST | `/v1/ingest/calls` | §4.3 |
| GET | `/v1/ingest/health` | agent connectivity + key check |

**Calls**

| Method | Path | Notes |
|---|---|---|
| GET | `/v1/calls` | cursor pagination (`?cursor=`, `?limit≤100`); filters: `from`, `to`, `q`, `intent`, `sentiment`, `number` |
| GET | `/v1/calls/{id}` | transcript + latest successful analysis |
| GET | `/v1/calls/{id}/audio` | 302 → 60s MinIO presign; org_admin/operator |
| POST | `/v1/calls/{id}/reanalyze` | new analysis_run; not re-billed |
| GET | `/v1/analytics/summary` | intent/sentiment counts per date range |

`q` searches `transcripts.search` (FTS) and numbers (`pg_trgm`).

**Billing**

| Method | Path |
|---|---|
| GET | `/v1/billing/balance` |
| GET | `/v1/billing/ledger` |
| GET | `/v1/billing/packages` |

**Webhooks**

| Method | Path |
|---|---|
| POST | `/v1/webhooks` |
| GET | `/v1/webhooks` |
| DELETE | `/v1/webhooks/{id}` |

**Admin** (staff JWT): tenant CRUD, suspend, top-up, KPIs, job re-queue, settings (`asr_model`, `llm_model`, `prompt_version`), audit log.

---

## 12. Web panels

React + TypeScript + Tailwind, RTL (`fa`). Recharts for charts.

**Client (tenant):** login · overview (balance in toman + minutes, call counts, sentiment pie, last 10 calls) · calls list with filters + detail (transcript with channel colors, NER highlights, action-item checklist) · analytics (sentiment trend, intent bars) · account (users, API keys, webhooks, profile) · install page (dialplan snippet, agent download, `/v1/ingest/health` tester).

**Admin (staff):** separate auth, no shared session. KPIs · tenant table/detail · top-up · suspend · queue depth + failed-job re-queue · packages · audit log.

---

## 13. Security

- TLS در Nginx Proxy Manager بیرونی؛ دسترسی پورت‌های production فقط از IP همان پراکسی
- Passwords argon2id; API keys stored as `sha256(secret + pepper)`, prefix shown only
- Audio object keys `{tenant_id}/{call_id}.wav` — no phone numbers in keys; presigned URLs expire in 60 s
- RLS + `tenant_id` on every customer-data table
- Rate limits: 30 uploads/min per key, 120 GET/min per user
- Retention job deletes MinIO objects past `audio_retention_days` (via `audio_objects.expires_at`); transcripts kept until tenant-requested deletion
- Tenant delete/export endpoints (hard delete, JSON/CSV export)
- Secrets never in git; audit every staff mutation

---

## 14. Deployment

Ubuntu 24.04 LTS, Docker Compose.

| Service | Replicas | CPU | RAM |
|---|---|---|---|
| client / admin | 1 each | 0.5 each | 256 MB each |
| api | 1 container / 2 Uvicorn workers | 2 | 4 GB |
| worker-asr | 4 | 1–2 each | 512 MB each |
| llama-server | 2 | 20–24 each | 20 GB each |
| worker-llm | 2 | 1 each | 512 MB each |
| worker-notify | 1 | 0.5 | 512 MB |
| postgres | 1 | 4 | 24 GB |
| redis | 1 | 1 | 4 GB |
| minio | 1 | 1 | 2 GB |
| prometheus + grafana + loki | 1 | 2 | 4 GB |

Keep ≥ 8 cores and ≥ 80 GB RAM free; llama-server already takes ~40–48 cores.

Capacity at 300 h/day:

| Resource | Math | Result |
|---|---|---|
| ASR | 300 h × RTF 0.075 | 22.5 core-hours — trivial for 4 workers |
| LLM | ~6,000 calls × ~40 s ÷ 8 slots | fits a 10-hour business-day burst |
| Audio | ~115 MB/h × 300 h | ~35 GB/day → ~1 TB per 30-day retention |
| Postgres | transcripts + JSON | tens of GB |

Bottlenecks in order: LLM slots, then disk. NVMe ≥ 2 TB usable.

---

## 15. Observability

- `/healthz` (liveness) and `/readyz` (postgres/redis/minio/llm ping) on every process
- JSON logs: `timestamp`, `level`, `service`, `request_id`, `tenant_id`, `call_id`, `message`
- Metrics: ingest count, queue depth + job wait, ASR seconds processed, LLM tokens/s, JSON parse failure rate, credit rejects, webhook 4xx/5xx
- Grafana: pipeline funnel by `calls.status`, queue lag, llama-server CPU
- Alerts: llama-server down, postgres down, `failed_retryable` > 50 for 10 min, disk > 80%

---

## 16. Implementation plan

Each phase gates the next on its acceptance test.

| # | Phase | Deliverable | Accept |
|---|---|---|---|
| 0 | Infra | Compose: پورت‌های محدود برای NPM، Postgres، Redis، MinIO و monitoring | `curl https://api…/healthz` = 200 از مسیر NPM |
| 1 | Schema + auth | Alembic baseline, RLS, login/refresh, API keys | tenant B cannot read tenant A rows |
| 2 | Ingest + reserve | Multipart upload, ffprobe, MinIO put, reservation | duplicate uniqueid → same `call_id`; zero balance → 402, nothing stored |
| 3 | ASR worker | Channel split, Shenava, utterances + transcript | fixture WAV → stable text, status `transcribed` |
| 4 | LLM worker | llama-server, schema validation, repair, chunking | fixture transcript → valid JSON; 30-min transcript not truncated |
| 5 | Settle + notify | Ledger settle/release, HMAC webhooks, retries | success charges once; crash-then-success charges once; terminal fail charges zero |
| 6 | Agent | AMI hangup → merge → upload → retry | live Asterisk call lands in DB, call not dropped |
| 7 | Client panel | Dashboard, calls, analytics, account, install | org_admin full walkthrough without API tools |
| 8 | Admin panel | Tenants, top-up, re-queue, KPIs, audit | support top-up + re-run appear in `audit_events` |
| 9 | Hardening | 300 h fixture load in 24 h, retention, backup + restore drill | p95 ingest→complete < 5 min (un-backlogged); burst backlog drains before next business day |

**First vertical slice (weeks 1–2, phases 0–5 minimal):** seed a tenant with credit → `curl` a stereo WAV → status reaches `complete` → `GET /v1/calls/{id}` returns transcript + insights → ledger shows one reservation and one settlement. No UI. This slice is the product.

---

## 17. Open questions (owners needed)

1. Shenava-Koochik artifact + license for production (`tract` vs ONNX) — blocks §9.1 internals, not the interface
2. Dorna GGUF source; Q4_K_M quality on ASR-noisy text — blocks §9.2 internals
3. MixMonitor ownership: we ship the snippet, or require a fixed context name
4. `agent_extension` → panel user mapping for operator stats
5. Consent announcement flag (legal) — v1.1 candidate

Until 1–2 are resolved, develop `AsrEngine` / `LlmClient` against fixtures; nothing else blocks.
