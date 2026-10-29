---
name: sedasanj-logging-standard
description: Write logs for the FreePBX engine (PHP) and SedaSanj services (Python) in the shared JSON-lines format with redaction and correlation IDs. Use when adding or reviewing any log statement.
---

# Logging standard

## Format (target; plan section 6)

JSON lines with `ts` (ISO‑8601 with offset and ms), `level`, `component`, `event`, `code` (`SS-…`), `msg`, `pid`, `host`, and `ctx` (`uniqueid`, `linkedid`, `trace_id`, `job_id`, `ext`, `file`, `http_status`, `server_request_id`, `duration_ms`, `attempt/max`, `bytes`, `curl_errno`).

## Current state (verified)

- Python API: `sedasanj/apps/api/app/logging.py` already emits JSON with `request_id`, `tenant_id`, `call_id` context variables.
- PHP engine: `freepbx-module/engine/src/Logger.php` is plain text; `engine/bin/mix-stereo.php` logs only to STDERR. Migration to the JSON format and a shared Logger is planned.

## Rules

1. Never log API keys, archive passwords, `sk_live_*` tokens, `Authorization` / `X-CBI-Archive-Password` headers, or full phone numbers (mask by default).
2. Strip control characters from interpolated values (log forging).
3. Log files are mode 0640. Rotation via logrotate (daily, 14 days, `copytruncate`) is the planned replacement for manual rotation.
4. Carry `trace_id` from the hook through sidecar/state/job/manifest; send `X-Request-ID` and record the server's returned request ID.
5. Every error log has a `code`; WARN/ERROR without a code is a bug.
6. Redaction lives inside the Logger, not at call sites.

## How to verify

Unit test the redactor with each secret shape; run a failing upload against a stub server and check the log line has code, trace_id and no secret; `ruff check . && mypy apps` for Python changes.
