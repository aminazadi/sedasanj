---
name: freepbx-module-lifecycle
description: Change the install, upgrade, uninstall, backup and dependency behaviour of the Seda Sanj `recuploader` FreePBX module across FreePBX 15, 16 and 17. Use for module.xml, BMO hooks, zip layout and the two-phase install.
---

# FreePBX module lifecycle (`recuploader`)

Official sources: FreePBX `framework` repository, branch `release/17.0` (`modulefunctions.class.php`, `GPG.class.php`, `Console/Moduleadmin.class.php`, `BMO/Job.class.php`). Anything below marked **⚠ needs lab confirmation** was read from source or docs but not yet run on a real PBX; do not present it as verified.

## Contract (verified from FreePBX source, per the approved plan)

- Module Admin upload accepts tar/tgz/tar.gz/bz2/zip (zip needs the `unzip` binary). If `module.xml` is not at the archive root there must be exactly one subdirectory. The target directory is named from `<rawname>`; the old directory is removed with `rm -rf` and replaced with `cp -R`.
- After extraction only `bin`, `hooks` and `agi-bin` directories are `chmod 755`. Anything executable elsewhere (for example `engine/bin/*`) must be chmod-ed by our own install code.
- `install()` order: status check, `GPG->verifyModule` (only a **revoked** module is blocked; unsigned installs), `checkdepends`, install callback, `<database>` table migration, BMO `install()`, row in `modules`, `needreload()`.
- `checkdepends` understands `version`, `phpversion`, `phpcomponent` (`||` means OR), `module` (with version operator), `file`, `engine` (e.g. `asterisk 18`). Failures are returned before `install()` runs, and Module Admin offers dependencies itself.
- `fwconsole ma` subcommands: `install uninstall upgrade upgradeall download downloadinstall enable disable delete list listonline showupgrades reversedepends installlocal`. `installlocal` installs all local modules; it does not upload. Use `downloadinstall <module>` for official-repo dependencies.
- BMO class entry points: `install()`, `uninstall()`, `backup()`, `restore()`, `ajaxHandler()` (see `freepbx-module/Recuploader.class.php`).

## Two-phase install (target design)

- **Phase A (no root, from Module Admin):** check PHP version and extensions, FreePBX version, write the engine into the module directory, record `needs_activation`. No systemd, sudoers, backup or core patch. A failure must produce a coded error (see `sedasanj-error-codes`), never a half-installed module.
- **Phase B (root):** `activate.sh` (planned, `freepbx-module/activate.sh`) does backup, systemd, sudoers, helper, logrotate, hooks/globals and health check. `install.sh` (SSH) must call the same script so there is one source of truth.
- The existing `freepbx-module/install.sh` states that `fwconsole ma installlocal` did not work in practice; do not rely on it for upload-style installs.

## Support matrix

| FreePBX | Web PHP | Asterisk | Status |
|---|---|---|---|
| 17 | 8.2 (Debian 12) | 21/22 | Tier 1 |
| 16 | 7.4 | 16/18/20 | Tier 1; do not target PHP 8.x |
| 15 | 5.6 base (7.3 on Debian 10 guide) | 13–18 | Tier 2, best effort (see `freepbx-php-compat`) |

⚠ Asterisk 16/18 EOL status must be confirmed against the official lifecycle page.

## Repo ownership

- Module metadata: `freepbx-module/module.xml` (currently has no `<depends>`/`<supported>`; adding them is part of the plan).
- BMO class and admin page: `freepbx-module/Recuploader.class.php`, `freepbx-module/page.recuploader.php`.
- Installers: `freepbx-module/install.sh`, `uninstall.sh`, `backup-installation.sh`, `restore-installation-backup.sh`, updater helper `freepbx-module/bin/sedasanj-recuploader-update.sh`.
- Engine: `freepbx-module/engine/` (`bin/`, `src/`, `config/config.ini.example`).
- Release build: `scripts/build-freepbx-module-release.sh`. Versions must agree in `module.xml`, `freepbx-module/changelog.md` and `freepbx-module/README.md`.
- Planned (do not reference as existing): `compat-matrix.json`, `activate.sh`, Dependencies/Health tab.

## How to verify

1. `php -l` every changed PHP file under each supported PHP (needs PHP; it is not installed on the maintainer's Mac, so use a container).
2. Run `freepbx-module/tests/*` (`CdrSourceTest.php`, `ConfigProfileContractTest.php`, `ModuleUpdateTest.php`, `PageContractTest.php`).
3. Lab matrix: install from Module Admin (zip upload), install via SSH, upgrade, uninstall, reinstall, on each FreePBX version. State which cells were not run.
