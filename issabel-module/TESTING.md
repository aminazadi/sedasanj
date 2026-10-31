# Issabel beta validation

## Automated checks

- PHP 5.6: web/lifecycle lint, authenticated bridge/CSRF tests and official 2.11/2.12 recording fixtures.
- PHP 7.4 and 8.2: complete module/engine lint, settings roundtrip, input rejection, adapter checks and strict TGZ extraction tests.
- Existing FreePBX module tests: PHP 7.4 and 8.2 regression matrix.
- API: release product isolation, unknown-host rejection, PHP/Issabel compatibility, TAR links/devices/traversal/duplicates, key embedding, manifest constraints, stable-promotion gate and help-catalog parity.
- PostgreSQL: upgrade/downgrade/re-upgrade on the actual module/help schemas (0053–0056), including six help articles. Full migration history requires an Apache AGE-enabled PostgreSQL instance; plain pgvector alone stops at the pre-existing 0037 revision.
- Admin/client production builds; legacy PHP-rendered page JavaScript syntax check.

PHP 5.4 execution: **NOT RUN**. The official image uses a retired Docker schema-1 manifest rejected by the installed containerd. The web code deliberately avoids PHP 5.5+ syntax, but this is not a substitute for a PHP 5.4 runtime test.

## PBX lab matrix — all NOT RUN

| Distribution | Web PHP | CLI PHP | Asterisk | Install / upgrade / rollback | Calls / stereo / CDR playback |
|---|---|---|---|---|---|
| Issabel 4 | stock 5.4/5.6 | separate 7.4+ | 11 | NOT RUN | NOT RUN |
| Issabel 4 | stock 5.4/5.6 | separate 7.4+ | 13 | NOT RUN | NOT RUN |
| Issabel 4 | stock 5.4/5.6 | separate 7.4+ | 16 | NOT RUN | NOT RUN |
| Issabel 5 | 7.4 | 7.4+ | 16 | NOT RUN | NOT RUN |
| Issabel 5 | 7.4 | 7.4+ | 18 | NOT RUN | NOT RUN |

For each row verify GUI upload, SSH installation, activation, upgrade, failed-upgrade rollback, uninstall/reinstall, inbound/outbound/internal calls, queue, transfers, on-demand recording, missed calls and voicemail. Check one received server record, stereo channel orientation and original CDR playback. Test network/TLS/auth/credit failures, low disk, CDR delay/missing columns, duplicate hooks, service restart and SELinux enforcement.

No row is certified by fixture tests. Record exact OS/framework/PHP/Asterisk versions, redacted logs and stable error codes. Keep releases on beta; the super-admin certification action requires evidence for the exact release artifact before stable promotion.
