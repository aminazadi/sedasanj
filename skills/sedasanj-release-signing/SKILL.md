---
name: sedasanj-release-signing
description: Publish, rotate and recover the Ed25519 signing of Seda Sanj FreePBX module releases and their update manifest. Use for release publishing, key handling and updater verification changes.
---

# Release signing

## Verified current behaviour

- The server signs the ASCII sha256 hex digest of the release zip with an Ed25519 key (detached, base64): `sedasanj/apps/api/app/services/module_releases.py` (`_signing_key`, signature helper near line 156). The seed lives at `/module-release-signing/private.seed` in the API container; `sedasanj/scripts/backup.sh` copies it to `module-release-signing.seed` (mode 600).
- The public key is embedded in every published zip as `recuploader/assets/release-signing.pub` (`freepbx-module/assets/release-signing.pub` in the repo is the build placeholder/source). The root helper `freepbx-module/bin/sedasanj-recuploader-update.sh` re-verifies against `/etc/sedasanj-recuploader-update/release-signing.pub`.
- Release rows: `module_releases` (migration `0053_module_releases.py`) with channel `stable|beta`, status `draft|published|revoked`, `min_freepbx_major`, `min_from_version`.

## Planned hardening (not implemented; do not describe as existing)

Signed manifest (version, sha256, size, min/max FreePBX, channel, issued_at, expires_at); updater rejects downgrade and expired manifests and logs `key_id`; two valid public keys at once for rotation; admin panel shows key fingerprint; no silent key generation; staged rollout, per-installation channel, rollback pointer; second-factor confirmation for publish/revoke via `_verify_sensitive_staff_action` (`sedasanj/apps/api/app/routers/admin.py`).

## Release checklist

1. Versions equal in `freepbx-module/module.xml`, `freepbx-module/changelog.md`, `freepbx-module/README.md`.
2. Tests pass; `tests/` is excluded from the zip.
3. The zip does not contain the placeholder public key and contains the real one (`scripts/build-freepbx-module-release.sh`).
4. Publish as draft, verify sha256/signature with an independent script, then publish.
5. Back up the signing seed (see `sedasanj-backup-restore`) before any rotation. Losing the seed means installed modules can no longer verify updates until a manual key replacement: document the recovery path before rotating.

Never print, log or commit the seed.

## How to verify

`cd sedasanj && pytest tests/test_module_releases.py`; lab: update from N-1 to N, and a forced failure after swap triggers rollback (⚠ lab).
