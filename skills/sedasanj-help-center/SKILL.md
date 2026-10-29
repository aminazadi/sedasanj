---
name: sedasanj-help-center
description: Author and build the SedaSanj help center (error-code articles with text, images and video) in the API, admin panel and public web app. Use when writing articles or touching the help data model or editor.
---

# Help center

## Design (from the approved plan; mostly not yet implemented)

- Data (planned migration `sedasanj/apps/api/alembic/versions/0054_help_center.py`, `down_revision = "0053_module_releases"`): `help_categories`, `help_articles`, `help_media`, `help_error_codes`, `help_feedback`. Global tables, no `tenant_id`/RLS, like `module_releases`.
- API (planned): public `GET /v1/help/...` in `routers/help.py`; admin `/v1/admin/help/*`, writes limited to `super_admin`, each write calls `audit.record`.
- Public routes `/help`, `/help/:slug`, `/help/errors/:code` must be added to **both** route sets in `sedasanj/web/client/src/App.tsx`.
- ⚠ `sedasanj/deploy/web-server.mjs` (about line 62) 404s paths containing a dot outside `/assets/`; keep slugs dot-free or fix the server.

## Article structure (every error article)

Symptoms → Cause → Fix (numbered steps, copyable commands) → How to confirm → Prevention. Title and body in Persian; the error code, commands, paths and filenames stay LTR English (`dir="ltr"`) with Latin digits.

## Content safety

- Sanitize HTML on the server with one shared allowlist (today `sanitize_changelog` in `sedasanj/apps/api/app/services/module_releases.py`; plan extracts a shared `sanitize_help_html`) and mirror it in `sedasanj/web/admin/src/sanitize.ts`.
- Video only from our own storage or an allowlisted host in a sandboxed frame; no free-form iframes.
- Media upload: size cap and MIME allowlist; follow the `_spool_upload` pattern in `routers/module_updates.py`.
- Feedback rows hold no personal data.

## How to verify

Render the article in RTL; check the code deep link from the module resolves; sanitizer tests with script/onerror/`javascript:` payloads; `cd sedasanj/web/admin && npm run build` and the same in `web/client`.
