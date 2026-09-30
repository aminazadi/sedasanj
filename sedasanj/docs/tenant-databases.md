# Tenant databases runbook

## Topology

The `cbi` database is the control plane. Every ready organization is routed to a dedicated
`cbi_tenant_<tenant-uuid>` database in the same PostgreSQL cluster. Runtime requests never
accept a database name or tenant identifier from request data; the signed tenant claim is
resolved through `tenant_database_registry`.

## Bootstrap

Set `TENANT_DATABASE_MASTER_KEY` to a Fernet key, keep `PROVISIONER_DATABASE_URL` restricted
to the provision worker, and enable `TENANT_DATABASES_ENABLED`. The PostgreSQL image contains
the pinned pgvector and Apache AGE binaries. The provision worker creates roles, databases,
extensions, schemas, graph storage, grants, identity records, and health checks automatically.

Users and API keys remain authoritative in the control plane. User changes create a durable,
versioned projection event. The provision worker applies the projection idempotently to the
tenant database; until that succeeds, a new operator has no tenant-data access.

## Existing organizations

With `TENANT_DATABASE_AUTO_MIGRATE=true`, the provision worker discovers legacy organizations
without a registry record and processes one organization at a time. It creates the target,
places only that organization in maintenance mode, copies tenant-scoped data in dependency
order, validates counts, activates the registry, and keeps the legacy source rows through the
configured rollback window. Failed work remains retryable from Admin > Tenant Databases.

The same worker upgrades ready databases sequentially to the application schema head. A failed
fleet migration removes the database from routing until an administrator retries it; rollout
does not continue silently after a failed database.

## Operational checks

- Confirm the target database identity equals the signed tenant ID.
- Confirm `vector` and `age` are installed and the `tenant_graph` graph exists.
- Confirm the tenant runtime role is not superuser, `CREATEDB`, `CREATEROLE`, or `BYPASSRLS`.
- Monitor database count, connections, disk, WAL, autovacuum, migration duration, and failures.
- Keep tenant database credentials out of Redis payloads and logs.
- Verify the automated encrypted per-database dump status and checksum in Admin > Tenant
  Databases. Dumps include graph and vector storage and expire under the configured retention
  policy. Cluster-level WAL archiving remains a deployment responsibility because PostgreSQL
  performs PITR at cluster scope.

## Recovery

Do not delete legacy rows at cutover. If validation fails, the registry remains inactive and
the source stays authoritative. If a post-cutover issue occurs, place the tenant in maintenance,
reconcile the target delta before changing the registry, invalidate its pool, and audit the
operation. Never point the registry at an unvalidated database.
