# Audit 3 — remediation plan

Third full pass of the codebase against the original plan. Focus: production
readiness. No end-to-end testing was performed (per instruction); every fix is
covered by static checks and unit tests.

## Findings and fixes

### High

1. **Admin model settings were write-only.** `PATCH /v1/admin/settings` stored
   `llm_model` / `prompt_version` / `asr_model` in `platform_settings`, but
   nothing read them back: new analysis runs always used the env defaults.
   Fixed with `app/services/platform.py` (`effective_models`), used when
   creating analysis runs (reanalyze endpoint, admin requeue, LLM worker
   fallback). The LLM worker now also loads the prompt by the run's
   `prompt_version` instead of the env value, so a run is analyzed with the
   prompt it was created for.
2. **Suspended tenants could keep refreshing tokens.** `POST /v1/auth/refresh`
   never checked tenant status; a suspended tenant's users could mint access
   tokens for the whole refresh TTL. Refresh now re-validates tenant status.
3. **`queue_depth` gauge was never updated.** `refresh_queue_depth()` existed
   but had no caller, so the queue-backlog alert could never fire. The notify
   worker's reconciler cron now refreshes it every 10 minutes.
4. **Duplicate reanalysis jobs.** Every `POST /calls/{id}/reanalyze` inserted a
   new `jobs` row and enqueued another run even while one was still
   queued/running. The endpoint now returns `conflict_idempotency` while an
   LLM job for the call is active.

### Medium

5. **Ingest storage failure leaked internals.** The 500 response embedded the
   raw storage exception (endpoint host, boto error details). The detail is
   now logged server-side and the client gets a generic message.
6. **Missing explicit tenant predicates.** `billing.settle`/`billing.release`
   looked reservations up by `call_id` only, and `GET /v1/billing/ledger`,
   `GET /v1/auth/api-keys`, `GET /v1/auth/users` relied on RLS alone. All now
   carry explicit `tenant_id` filters (RLS stays the second line of defence).
7. **`verify_password` swallowed every exception.** `except (VerifyMismatchError,
   Exception)` hid unexpected runtime errors (including programming bugs) as a
   failed login. Narrowed to argon2's `VerificationError` / `InvalidHashError`.
8. **TOTP accepted any digit-only length.** Codes are now required to be
   exactly 6 digits.
9. **Production config allowed the default MinIO secret.** The production
   settings validator now rejects the shipped `cbi-secret` default and short
   values, alongside the existing JWT/pepper checks.

## Verified as correct (no change needed)

- Billing reserve/settle/release idempotency keys, ledger + cache in one
  transaction, no double charge on worker retries.
- Conditional `claim_call` state transitions; centralized retry scheduling in
  `pipeline.handle_failure`; reconciler covers commit-then-enqueue gaps.
- RLS context binding per transaction plus non-superuser runtime role check.
- Webhook HMAC signing, SSRF re-validation at delivery time, delivery records.
- Agent spool durability, dead-letter retention, permanent vs retryable
  rejection handling.
- Audio contract validation (WAV/PCM, 8/16 kHz, 1–2 ch) with `415
  unsupported_audio`; object keys contain no phone numbers.

## Out of scope (unchanged, per instruction)

- End-to-end tests, live Asterisk/Shenava/Dorna validation.
