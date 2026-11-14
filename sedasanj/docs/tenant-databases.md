# Tenant databases runbook

## Topology

The `cbi` database is the control plane. Every ready organization is routed to a dedicated
`cbi_tenant_<tenant-uuid>` database in the same PostgreSQL cluster. Runtime requests never
accept a database name or tenant identifier from request data; the signed tenant claim is
resolved through `tenant_database_registry`.

## Bootstrap

Set `TENANT_DATABASE_MASTER_KEY` to a stable high-entropy secret or Fernet key, keep
`PROVISIONER_DATABASE_URL` restricted to the provision worker, and enable
`TENANT_DATABASES_ENABLED`. Non-Fernet secrets are deterministically converted to a Fernet key,
so the value must remain unchanged after tenant credentials are encrypted. The PostgreSQL image contains
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

## Failure codes

Admin > Tenant Databases shows a stable code, a Persian message and the next action for each
failed organization; the full sanitized detail is under «جزئیات فنی». Codes: `TENANT_DB_KEY_INVALID`,
`TENANT_DB_WORKER_STALE`, `TENANT_DB_PREFLIGHT`, `TENANT_DB_PLAN_CONFLICT`,
`TENANT_DB_SCHEMA_REVISION`, `TENANT_DB_ALEMBIC_FAILED`, `TENANT_DB_DRAIN_TIMEOUT`,
`TENANT_DB_VALIDATION`, `TENANT_DB_UNKNOWN`. After every deploy restart `worker-provision` together
with the API so it runs the same schema head. Retry-all requeues every failed organization; the
worker still runs them one at a time.

## Backups

`worker-tenant-backup` dumps every `ready` tenant database (pgvector and the Apache AGE graph
included) every `TENANT_BACKUP_INTERVAL_HOURS`, encrypts it, uploads it and re-reads the object to
verify the checksum. Organizations that are still `Legacy` have no dedicated database yet and are
covered by the control-database backup until their migration completes. «پشتیبان‌گیری فوری» on
the admin page queues an immediate backup. A failed backup shows a `TENANT_BACKUP_*` code, the
next action and the sanitized pg_dump reason.

pg_restore keeps the source graph ids in `ag_catalog`, which AGE rejects. Every restore path
(`tenant_backup_restore.py`, `backup_lib.sh`) therefore runs the AGE repair before the database is
used; never restore a tenant dump with a bare `pg_restore`.

Test the whole pipeline against a disposable PostgreSQL (pgvector + AGE, `age` preloaded):
`TENANT_BACKUP_TEST_URL=postgresql+asyncpg://postgres:pw@127.0.0.1:55433/postgres pytest tests/test_tenant_backup_restore.py`.

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

## بک‌آپ و انتقال داده‌های کاری سازمان

مدیر سازمان از «تنظیمات حساب ← داده‌ها» کلید بازیابی را تولید و در جای امنی جدا
از فایل نگه می‌دارد. کلید جدید فقط فایل‌های بعدی را باز می‌کند. هنگام ورود، کلید
همان فایل لازم است. فایل‌های `.gzip` و `.sedasanj` را مستقیم در همین بخش
بارگذاری کنید. پیش‌نمایش، تعداد رکوردها و نگاشت اعضا را بررسی کنید و سپس ورود
را تأیید کنید. قالب `.gzip` داده‌های کاری و رسانه‌ها را به‌صورت بدون افت با
سطح `9` فشرده و سپس رمزگذاری می‌کند. این قالب نام حاضران و برچسب گویندگان
جلسه را نیز منتقل می‌کند. بازیابی حساب‌ها، اعتبارنامه‌ها، سوابق مالی، صف اجرا،
پروفایل‌های خصوصی و اثرهای صوتی به پشتیبان عملیاتی و کلیدهای همان نصب نیاز دارد.

- `worker-organization-data` را همراه API و پس از مهاجرت پایگاه داده اجرا کنید.
  `PLATFORM_SECRETS_KEY` در API و ورکر باید یکسان و پایدار باشد.
- پس از استقرار خوانندهٔ هر دو قالب، با `ORG_ARCHIVE_WRITE_V2=true` ساخت فایل‌های
  `.gzip` را برای دانلود دستی و ارسال زمان‌بندی‌شده فعال کنید. برای بازگشت به
  قالب تولید قبلی، این تنظیم را `false` کنید. بازیابی هر دو قالب فعال است.
- سقف پیش‌فرض فایل `ORG_ARCHIVE_MAX_BYTES=10737418240` و سقف دادهٔ بازشده
  `ORG_ARCHIVE_EXPANDED_MAX_BYTES=21474836480` است. هر فایل حداکثر ۵۰۰٬۰۰۰ رکورد دارد.
  برای هر بازیابی هم‌زمان در ورکر، فضای موقت را برای فایل ورودی، نسخهٔ
  فشردهٔ رمزگشایی‌شده، نسخهٔ بازشده و سربار ZIP در نظر بگیرید. فضای موقت API،
  سقف بارگذاری و مهلت پراکسی جلوی پنل را هم با این مقادیر هماهنگ کنید.
- مقصد پیش‌فرض FTPS صریح روی پورت `21` با گواهی معتبر و کانال دادهٔ غیرفعال است.
  پوشهٔ مقصد از قبل ساخته شود و حساب FTP مجوز نوشتن، خواندن، تغییر نام و حذف
  فایل موقت را داشته باشد. ورکر هش فایل موقت را پیش از انتشار در مقصد بررسی
  می‌کند. برای FTP عادی، `ORG_BACKUP_ALLOW_PLAIN_FTP=true` را
  در استقرار ثبت کنید و از حساب جداگانهٔ بک‌آپ استفاده کنید.
- فایل‌های داخلی بک‌آپ خودکار پس از ۳۰ روز و فایل‌های دستی یا در انتظار تأیید
  پس از ۲۴ ساعت پاک می‌شوند. برای مقصد FTP چرخهٔ نگهداری جداگانه تعریف کنید.
  از تب «داده‌ها» صفحهٔ «تاریخچهٔ بک‌آپ و بازیابی» را باز کنید. نتیجهٔ ساخت فایل،
  ارسال به مقصد و ادامهٔ بازیابی‌های ناتمام در همان صفحه در دسترس است.
- برای آزمون بازیابی، یک فایل با تماس، جلسه و صوت بسازید و در سازمان آزمایشی
  وارد کنید. پخش صوت، مالکیت و نتیجهٔ ورود مجدد فایل را بررسی کنید.
