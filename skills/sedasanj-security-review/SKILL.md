---
name: sedasanj-security-review
description: Security checklist for SedaSanj API, admin/web UI and the FreePBX module. Use when reviewing or writing code that handles input, files, URLs, auth or secrets.
---

# Security review checklist

1. **Injection into hooks/shell:** values reaching MixMonitor commands, `Process`/`exec`, `sudo` helpers or dialplan must be filtered/escaped (`FILTER()` in dialplan; argument arrays, never string concatenation). Helper `freepbx-module/bin/sedasanj-recuploader-update.sh` runs as root: validate every argument.
2. **Archives:** zip-slip, absolute paths, symlinks, decompression bombs, size caps (server side: `app/services/archives.py`; module side: updater and install).
3. **SSRF:** outbound URLs from admin/tenant config go through `app/services/urlguard.py`; disable redirects when sending credentials (see `skills/smsir-service-templates`).
4. **XSS:** admin-authored HTML uses the shared sanitizer (`sanitize_changelog`; `web/admin/src/sanitize.ts`). Never render unsanitized HTML.
5. **CSRF:** the FreePBX page and every `ajaxHandler` action must verify the FreePBX CSRF token (a case-insensitive grep for `csrf` in `page.recuploader.php` found nothing; ⚠ confirm how the FreePBX framework covers it).
6. **Rate limits and `client_ip`:** public endpoints rate-limit by IP via `app/services/ratelimit.py` and `deps.client_ip`; verify proxy-header trust.
7. **Authorization:** staff routes use `StaffDep`; destructive/sensitive staff actions use second-factor verification and `audit.record`.
8. **Secrets:** API keys, archive passwords, `JWT_SECRET`, `API_KEY_PEPPER`, `TENANT_DATABASE_MASTER_KEY`, `PLATFORM_SECRETS_KEY`, signing seed never appear in logs, responses, commits or screenshots.
9. **Headers/CSP:** check `sedasanj/deploy/web-server.mjs` responses.
10. **File permissions:** config/state/log files 0640 or tighter; root helpers verify ownership.

Report findings by severity with file:line and a concrete failing input.
