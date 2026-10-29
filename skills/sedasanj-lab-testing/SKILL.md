---
name: sedasanj-lab-testing
description: Run and report multi-version FreePBX lab tests (15/16/17) including canary calls and simulated failures. Use before claiming any module behaviour works.
---

# Lab testing

The maintainer's Mac has no PHP; everything PHP-related runs in containers or VMs. Lab scripts are planned under `scripts/lab/` (not present yet).

## Matrix (plan)

FreePBX 15 (PHP 7.4 lab; stock is 5.6/7.3), 16 (PHP 7.4, optionally 8.1/8.2 only as extra signal), 17 (Debian 12, PHP 8.2, Asterisk 21 or 22).

## Scenarios

1. Install via Module Admin zip upload, via SSH `install.sh`, upgrade, uninstall, reinstall.
2. Canary call: answered call with recording, unanswered call (`cdr.conf unanswered=yes`), voicemail. Expect exactly one server record each.
3. Failure simulation with a stub server (`php -S`): HTTP 401/402/404/413/415/422/429/5xx, timeout, connection refused, DNS failure, TLS error, clock skew.
4. Host faults: disk full, SQLite corruption, patch drift on `callrecording`, missing `sodium`.
5. Update: success, and failure after the swap with automatic rollback.

## Report format

For each cell (FreePBX version × scenario): PASS / FAIL / NOT RUN, log excerpt (redacted), error code seen, and the exact versions of FreePBX, Asterisk, PHP, OS. Explicitly list NOT RUN cells. Unverified FreePBX behaviour stays marked "⚠ needs lab confirmation" until a PASS is recorded.

## Existing automated tests

`freepbx-module/tests/` (`CdrSourceTest.php`, `ConfigProfileContractTest.php`, `ModuleUpdateTest.php`, `PageContractTest.php`, `fixtures/`) and server tests `sedasanj/tests/test_module_releases.py`, `test_ingest_config_validation.py`.
