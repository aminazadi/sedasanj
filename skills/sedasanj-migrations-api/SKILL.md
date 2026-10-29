---
name: sedasanj-migrations-api
description: Write Alembic migrations and API changes for the SedaSanj backend under this project's rules, with ruff, mypy and pytest. Use for any schema or `apps/api` change.
---

# Migrations and API

Work from `sedasanj/` (the Python project root, `pyproject.toml`).

## Alembic rules (verified from `apps/api/alembic/versions/`)

- Latest revision is `0053_module_releases`; new files continue the numeric prefix (`0054_…`) and set `down_revision` to the previous revision id. Keep a single head.
- One SQL statement per `op.execute(...)`, no trailing `;` (asyncpg runs them one at a time; see `tests/test_asyncpg_migrations.py`).
- Every new table needs `GRANT SELECT, INSERT, UPDATE, DELETE ON <table> TO cbi_app`.
- Tenant tables: `tenant_id`, `ENABLE` + `FORCE ROW LEVEL SECURITY`, policy on `app.tenant_id` / `app.staff` as in `0053`.
- Control-plane-only tables must be added to `_CONTROL_ONLY` in `apps/api/app/services/tenant_provisioning.py`, otherwise they are cloned into tenant databases. Global tables (no `tenant_id`) such as `module_releases` need the same consideration.
- Write a real `downgrade()`.
- Register models in `app/models.py` and `app/schemas.py`; routers in `app/main.py`.

## API rules

- Errors: `ApiError(code, message)` with the code in `ERROR_STATUS` (`app/errors.py`); add a test that every code maps.
- Sensitive staff actions call `_verify_sensitive_staff_action` (`routers/admin.py`); mutations call `app.services.audit.record`.
- Rate limits use `client_ip` (`app/deps.py`); ⚠ the plan lists a proxy-trust issue there (V1), review before relying on it.

## Commands

```bash
cd sedasanj
ruff check . && ruff format --check .
mypy apps
pytest
uv run alembic -c apps/api/alembic.ini upgrade head
```

ruff: line length 100, py312, rules E F I UP B ASYNC C4 SIM. mypy: strict. pytest: asyncio auto.
