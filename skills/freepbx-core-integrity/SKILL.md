---
name: freepbx-core-integrity
description: Keep the Seda Sanj module from tampering with signed FreePBX core modules and from creating command-injection risk in MixMonitor hooks. Use when touching core patches, globals_custom.conf or dialplan variables.
---

# FreePBX core integrity

## Contract

- FreePBX records signed file hashes in `module.sig`. Any registered file that changes is reported as `TAMPERED` with a security notice ("File … altered … compromised"). A module without `module.sig` is only `UNSIGNED` (a dashboard notice; install is not blocked). Source: `GPG.class.php`, `release/17.0`.
- Patching `callrecording/functions.inc.php` (what `freepbx-module/patch-callrecording.php` does today) therefore makes the core `callrecording` module appear tampered. Do not add new patches to signed modules. Prefer hooks and dialplan the module owns (`freepbx-module/dialplan/globals-custom-mixmon.conf`, `globals_custom.conf`).
- Any change to the existing patch must keep the rollback guarantee: checksum-verified original, restore only when the hash matches (see `freepbx-module/core-patches.json` and `README.md`).
- MixMonitor evaluates variables when the command runs. The Asterisk docs warn not to pass untrusted values such as `CALLERID(num)` into the command without `FILTER()`. Every dialplan variable we interpolate must be filtered or quoted.

## Rules

1. Read the current official source before editing a patch target; record which FreePBX versions the fixture covers.
2. Never edit files of signed modules unless the task is explicitly the patch workflow, with fixtures per supported version.
3. Add a drift test: the patch applier must refuse and report (coded error) when the target hash is unknown.
4. Dialplan/globals edits must preserve existing user content in `globals_custom.conf` (recent commits fixed global-state corruption; do not reintroduce it).
5. ⚠ Whether a fully patch-free design (FreePBX `Job` scheduler plus hook) is viable is unconfirmed; it is a lab spike, not a fact.

## Repo ownership

`freepbx-module/patch-callrecording.php`, `core-patches.json`, `dialplan/globals-custom-mixmon.conf`, `engine/bin/mix-stereo.php`, tests in `freepbx-module/tests/`.

## How to verify

Apply and revert the patch against fixtures from every supported FreePBX version; confirm `fwconsole` reports the core module unchanged after revert (⚠ lab); run the PHP tests; grep dialplan for unfiltered `CALLERID`/`CHANNEL` interpolation into commands.
