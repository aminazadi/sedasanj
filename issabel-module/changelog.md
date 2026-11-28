## 1.6.1 — 2026-11-26 — AMINAZADI

- Added installation guards: a mismatched Issabel bootstrap or framework version is rejected before anything is written.
- Moved the management-page JavaScript to `assets/admin.js` and kept the CSRF token in an escaped data attribute.
- Switched the admin stylesheet to the bundled Yekan Bakh fonts.
- Updated the shared engine: call-party resolution (answered extension versus dialed number, installation identity in extension sync), internal-call direction for `exten-*` recordings, dialplan labels never uploaded as call numbers, `SS-UPL-1004` CDR grace and `recover-unresolved.php`.
- Live PBX certification remains pending (⚠ needs lab confirmation).

## 1.6.0 — 2026-10-31 — AMINAZADI

- Added explicit Issabel bootstrap/framework guards and a standalone management UI asset.
- Added the Issabel 4/5 frontend with a PHP 5.4-compatible web gateway and an independent PHP 7.4+ engine.
- Added generated-dialplan integration, original recording preservation, CDR adapters, health checks and signed beta updates.
- Added mandatory verified installation backups and rollback; live PBX certification remains pending.
