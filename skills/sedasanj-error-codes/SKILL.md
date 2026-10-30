---
name: sedasanj-error-codes
description: Add or change a stable `SS-AREA-NNNN` error code for the FreePBX module with its catalog entry, help-center row, article and test. Use whenever a new failure mode appears.
---

# SedaSanj error codes

## Contract (design from the approved plan; the catalog is not yet implemented)

- Format `SS-<AREA>-NNNN`. Areas: `CFG SVC HOOK AUD STG UPL QUE SWP VMX MCP CDR SYS UPD DEP`.
- Catalog file (planned): `freepbx-module/engine/src/ErrorCatalog.php`. Each entry: code, title, severity, retryable, help slug, suggested action.
- Server mapping: table `help_error_codes` (code → article, severity, one-line summary, quick action, module catalog version) from migration `0054_help_center.py`.
- Public deep link: `https://<host>/help/errors/<CODE>?v=<module version>`.

## API codes (billing, plans, quota)

Backend API errors are stable snake_case codes in `app/errors.py` (`ERROR_STATUS`), with a `help_error_codes` row (`source = 'api'`) and a Persian article `error-<code>` seeded by migration `0069_billing_help_content.py`. Current set: `subscription_exists`, `change_conflict`, `plan_not_sellable`, `plan_in_use`, `plan_code_exists`, `order_amount_too_large`, `subscription_inactive`, `insufficient_credit`, `quota_exceeded`. A new API code needs: `ERROR_STATUS` entry, a help row and article (new migration, not an edit of 0069), a Persian mapping in `web/client/src/lib/billingErrors.mjs` when users can see it, and a test; `tests/test_billing_help_content.py` shows the completeness check. The FreePBX agent only sees the HTTP status (402 for `subscription_inactive`, `insufficient_credit`, `quota_exceeded`).

## Adding a code (all five, or it is not done)

1. Catalog entry.
2. Raise it from the failing path with `code` + `ctx`; persist it as `last_error` / in the failure manifest.
3. `help_error_codes` row.
4. Help article with symptoms / cause / fix / verification / prevention (`sedasanj-help-center`).
5. Test that triggers the path and asserts the code, plus a completeness test (every catalog code has a help row and article).

## Message rules

- Actionable: say what to check or run next. No dead ends.
- No secrets, no raw `repr(exc)`, no echo of caller input (API keys, archive passwords, phone numbers).
- Codes are never reused or renumbered; deprecate instead.
- Backend API errors use `app/errors.py` (`ERROR_STATUS`, `ApiError`); a new API error code must be added to `ERROR_STATUS` there.

## How to verify

`cd sedasanj && pytest tests/test_module_releases.py tests/test_provider_errors.py` for server side; PHP tests in `freepbx-module/tests/` for the catalog once it exists.
