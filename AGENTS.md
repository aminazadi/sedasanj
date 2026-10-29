# AGENTS.md — SedaSanj / Seda Sanj FreePBX module

Rules for every coding agent working in this repository. Skills with details live in `skills/<name>/SKILL.md`.

## Layout

- `sedasanj/` — Python 3.12 platform (API, workers, web). `sedasanj/apps/api` (FastAPI + Alembic), `sedasanj/web/{admin,client,shared}`, `sedasanj/deploy`, `sedasanj/scripts`, `sedasanj/tests`.
- `freepbx-module/` — the `recuploader` FreePBX module (PHP): BMO class, admin page, `engine/`, installers, tests.
- `aiservice/` — separate ASR service. `scripts/build-freepbx-module-release.sh` — module release build.
- Never commit `.DS_Store`, built `*.zip` archives, model downloads or secrets.

## General agent rules

1. **Read official sources first.** Before changing FreePBX/Asterisk behaviour, read the official FreePBX/Asterisk source or docs. Mark any claim you could not confirm as "⚠ needs lab confirmation"; do not state it as fact.
2. **Do not modify signed FreePBX modules** (e.g. `callrecording`) except through the documented patch workflow (`skills/freepbx-core-integrity`).
3. **Every behavioural change = test + error code + help article + changelog entry** (`skills/sedasanj-error-codes`, `skills/sedasanj-help-center`, `skills/sedasanj-changelog-commits`).
4. **Secrets never appear** in logs, error messages, commits, chat or screenshots: API keys, archive passwords, signing keys/seeds, `JWT_SECRET`, `API_KEY_PEPPER`, `TENANT_DATABASE_MASTER_KEY`, `PLATFORM_SECRETS_KEY`.
5. **Language:** user-facing UI and docs are Persian; identifiers, error codes, log messages, code comments and commit messages are English. Codes, commands and paths inside Persian text are LTR with Latin digits.
6. **PHP must run on 7.4** in the engine: no `match`, nullsafe `?->`, named arguments, constructor promotion or union types. The FreePBX web layer targets PHP 5.6 where FreePBX 15 is supported (`skills/freepbx-php-compat`).
7. **State and config files are written atomically** (write temp file in the same directory, then rename).
8. **No root or destructive operation without a verified backup** (`skills/sedasanj-backup-restore`). `sedasanj/scripts/restore.sh` restores into fresh databases and keeps the old ones as `_pre<stamp>`; it still stops all writers, so never run it on production without approval.
9. **Before saying "it works", run the tests** and say plainly what you did not run (e.g. PHP is not installed on the maintainer's Mac; lab matrix not run).
10. **Never leave the user without a next step:** every error message names an action.

## Python (`sedasanj/`)

```bash
cd sedasanj
ruff check . && ruff format --check .
mypy apps
pytest
```

ruff: line length 100, py312. mypy: strict. pytest: asyncio auto mode, tests in `sedasanj/tests/`.

### Alembic

Migrations: `sedasanj/apps/api/alembic/versions/`; latest is `0053_module_releases`; continue numbering and keep one head. One SQL statement per `op.execute`, no trailing `;`; `GRANT … TO cbi_app` for each table; tenant tables get RLS; control-plane tables go in `_CONTROL_ONLY` (`app/services/tenant_provisioning.py`); write a real `downgrade()`. Details: `skills/sedasanj-migrations-api`.

Apply: `uv run alembic -c apps/api/alembic.ini upgrade head` (from `sedasanj/`).

## FreePBX module (`freepbx-module/`)

- Tests: `freepbx-module/tests/*.php`. `php -l` on every changed file under each supported PHP, in a container.
- `module.xml` version, `freepbx-module/changelog.md` and `freepbx-module/README.md` must agree for a release (`scripts/build-freepbx-module-release.sh`).
- Support target: FreePBX 16 and 17 first; 15 best effort (Tier 2).

## Changelog

Root `CHANGELOG.md` format:

```
## YYYY-MM-DD — AMINAZADI

- Fixed <what> …
```

English, one bullet per change, newest date first. A second changelog exists at `sedasanj/CHANGELOG.md`; which one is canonical is an open maintainer decision. Until it is decided, add one entry to the changelog of the area you changed (module/repo-wide: root; platform: `sedasanj/`) and do not copy it into the other.

## Skills index

`freepbx-module-lifecycle`, `freepbx-core-integrity`, `freepbx-php-compat`, `asterisk-recording-pipeline`, `sedasanj-error-codes`, `sedasanj-logging-standard`, `sedasanj-release-signing`, `sedasanj-help-center`, `sedasanj-lab-testing`, `sedasanj-migrations-api`, `sedasanj-changelog-commits`, `sedasanj-security-review`, `sedasanj-backup-restore`, `sedasanj-pipeline-failure-classification`, `sedasanj-observability-alerts`, `smsir-service-templates`.
