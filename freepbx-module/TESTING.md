# Real-environment test guide (FreePBX 16 / 17, and 15 with PHP 7.4)

Everything below was verified only in containers (PHP 7.4 to 8.3, stub servers, PostgreSQL 16). It has **not** run on a real FreePBX/Asterisk. Test in this order on a non-production PBX first, and keep a snapshot.

## 0. Before you start
- Build the package: `scripts/build-freepbx-module-release.sh` (runs the tests, needs the vendored binaries, see the script header).
- Note versions: `fwconsole --version`, `asterisk -V`, `php -v` (CLI) and the PHP used by the web GUI.
- Have an API key and the import file `sedasanj-freepbx-config.json` from the Seda Sanj panel.

## 1. Install from the panel (the main change)
1. Admin > Module Admin > Upload modules > the ZIP > install.
   - Expected: succeeds as the web user. If Module Admin lists missing dependencies, install them first (that is the `<depends>` check).
   - If it fails, copy the exact message: it should carry an `SS-...` code.
2. Open Admin > Seda Sanj. Expected: the yellow **Activation required** notice with `sudo bash .../activate.sh`.
3. Run that command as root. Expected: `provisioned`, exit 0; reload the page: the notice is gone.
4. Check: `systemctl status asterisk-recording-uploader`, `asterisk -rx 'dialplan show globals' | grep MIXMON`, and `php .../patch-callrecording.php status /var/www/html/admin/modules/callrecording/functions.inc.php 0 /var/lib/asterisk-recording-uploader` (expected `patched`).
5. Tab **Health & Dependencies**: all required rows green. Try the one-click install on a module you removed on purpose.

## 2. Hook security (do this before any production exposure)
- Verify the filter really removes shell metacharacters: place a test call whose caller ID user part is `1001$(touch /tmp/ss-injection-test)` (or send it with `sipp`). **No `/tmp/ss-injection-test` file may appear**, and the recording must still be uploaded or logged with `SS-HOOK-1002`.
- If `FILTER()` drops hyphens from file names (recordings not found), tell me: the allowed-character list in `dialplan/globals-custom-mixmon.conf` needs adjusting.

## 3. Recording flow
- Inbound, outbound, internal, queue and ring-group calls; short and 30+ minute calls.
- Expected: uploaded, left/right channels correct (caller vs agent) and the same for both directions (the mapping is fixed: `recv_`=left). Report any inverted direction.
- Break things on purpose and check the code in the log and the help page: wrong API key (`SS-UPL-0401`, calls pause, fix key, they resume), endpoint without `/calls` (`SS-CFG-1004`), unplug network (`SS-UPL-2xxx`, retries), recording format not WAV (`SS-HOOK-1003`, mono copy delivered).
- `php /usr/local/bin/asterisk-recording-uploader/bin/doctor.php` and `.../requeue-failed.php --dry-run`.

## 4. Core patch drift
- Upgrade the FreePBX `callrecording` module (or reinstall it): the dashboard will show it as modified before activation; the Health tab must show the patch as missing; `activate.sh` restores it. Note the exact FreePBX dashboard message for the help article `SS-HOOK-1005`.

## 5. Update and rollback
- Publish a test release newer than the installed one from the admin panel (needs your password/TOTP), then **Update** in the module page. Expected steps: verify, extract, backup, swap, install, activate, reload, health, report.
- Failure test: publish a release whose `module.xml` version differs from the manifest or whose zip is corrupt: the update must refuse and the old version keeps working.
- Rollback test: make the activate step fail (for example `chmod 000` on the new `activate`-related path in a test copy) and confirm the previous version and the backup are restored.

## 6. Help center and fleet
- Admin > مرکز راهنما > کدهای خطا > "افزودن کدهای ماژول", then create/publish an article for `SS-UPL-0401` and open `/help/errors/SS-UPL-0401` logged out.
- Admin > سرورهای FreePBX > گزارش سلامت shows the host after about 5 to 10 minutes (the service reports hourly; run `doctor.php --report` to force one).

## What to send back
Exact error codes and messages, `doctor.php --json` output, the log lines around any failure and the Health tab screenshot. A support bundle (Health tab, or `support-bundle.php`) contains all of it with secrets removed.
