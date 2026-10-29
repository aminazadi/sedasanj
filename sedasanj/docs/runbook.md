# راهنمای عملیات (Runbook)

## سلامت روزانه

- `GET /healthz` سبک است؛ `GET /readyz` وضعیت Postgres، Redis، MinIO و llama-server را می‌دهد.
- داشبورد Grafana «Pipeline»: نرخ ingest، عمق صف، صدک ۹۵ انتظار کار، خطای JSON مدل، پاسخ وب‌هوک.
- هشدارهای Prometheus در `deploy/prometheus/alerts.yml`.

## عیب‌یابی

| نشانه | بررسی | اقدام |
| --- | --- | --- |
| صف ASR رشد می‌کند | `docker compose logs worker-asr` | افزایش replicaهای ورکر ASR (`deploy.replicas` در compose؛ `--workers` در این پروژه استفاده نمی‌شود) |
| صف emotion رشد می‌کند | `docker compose logs worker-emotion` و مصرف CPU/RAM | ابتدا cache مدل و سپس `MAX_CONCURRENT_EMOTION_JOBS` را بررسی کنید؛ افزایش هم‌زمانی RAM بیشتری مصرف می‌کند |
| `emotion_failed` | timeline پردازش و لاگ `worker-emotion` | دسترسی به مدل، revision، فضای volume و محدودیت ۴GB حافظه را بررسی کنید؛ تحلیل متن پس از خطای نهایی ادامه می‌یابد |
| خطای JSON مدل زیاد است | لاگ ورکر LLM، دقت prompt_version | بازگردانی نسخه پرامپت یا کاهش طول chunk |
| `llm_provider_timeout` | ثبت کار، polling یا دریافت نتیجه به مهلت نرسید | وضعیت کار و صف VoiceSanj، تنظیم آدرس پایه در پنل و `VOICESANJ_POLL_TIMEOUT_SECONDS` را بررسی کنید؛ تلاش مجدد با همان Idempotency-Key است |
| `llm_provider_task_failed` | سرویس وضعیت نهایی failed/cancelled گزارش کرده است | خطای نهایی سرویس، مدل انتخابی و تنظیمات را بررسی کنید؛ ارسال همان درخواست دوباره نتیجه متفاوتی نمی‌دهد |
| تماس‌ها در `failed_retryable` مانده‌اند | صفحه «کارهای ناموفق» در پنل مدیریت | اجرای مجدد کار؛ بررسی خطا |
| `insufficient_credit` | اعتبار مشتری در پنل مدیریت | شارژ دستی از صفحه مشتری |
| llama-server down | `docker compose ps llm1 llm2` | ری‌استارت سرویس؛ بررسی حافظه |
| تماس بدون تغییر وضعیت | outbox هر ثانیه تحویل را تکرار می‌کند و reconciler حداکثر ظرف یک دقیقه کارهای گیرکرده را بازیابی می‌کند | عمق outbox، سن قدیمی‌ترین job و لاگ worker-notify را بررسی کنید؛ تحلیل مجدد دستی لازم نیست |
| `asr_preprocessing_failed` | لاگ `worker-asr` و مدل‌های صوتی پنل | نام پروفایل را بررسی کنید؛ با نمونه WAV واقعی تست و سپس کار را دوباره اجرا کنید |

## حذف صوت و نگهداشت

نگهداشت صوت برای هر مشتری قابل تنظیم است (`audio_retention_days`، پیش‌فرض ۳۰ روز).
`app.services.maintenance.run_retention` فقط آبجکت صوتی را حذف می‌کند؛ متن و تحلیل باقی می‌ماند.
حذف کامل داده‌های یک مشتری از پنل مشتری (`DELETE /v1/account/data`) انجام می‌شود.

## پشتیبان‌گیری و بازیابی

```bash
export BACKUP_DIR=/srv/backup
export BACKUP_PASSPHRASE_FILE=/root/.cbi-backup-passphrase   # رمز بسته‌ی اسرار؛ خارج از سرور هم نگه دارید
export BACKUP_OFFSITE_TARGET=backup@other-host:/srv/cbi      # rsync؛ یا مسیر یک mount خارج از این هاست
./scripts/backup.sh
```

هر پشتیبان (`$BACKUP_DIR/<UTC stamp>/`) شامل این‌هاست:

| فایل | محتوا |
|---|---|
| `cbi.dump` | پایگاه کنترل (`pg_dump -Fc`) |
| `tenants/cbi_tenant_<uuid>.dump` | یک dump برای هر پایگاه مشتری |
| `secrets.tar.enc` | رمزشده با AES‑256: `deploy/.env` (شامل `TENANT_DATABASE_MASTER_KEY`، `PLATFORM_SECRETS_KEY`، `JWT_SECRET`، `API_KEY_PEPPER`)، نقش‌های پایگاه (`pg_dumpall --roles-only`) و کلید امضای ماژول |
| `SHA256SUMS`, `MANIFEST`, `audio.manifest` | یکپارچگی و فهرست اشیای صوتی |

نکات:

- هر dump با `pg_restore --list` بررسی می‌شود، ابتدا با نام موقت نوشته و سپس rename می‌شود؛ پوشه‌ی در حال ساخت `*.partial` است و هرگز برای restore استفاده نمی‌شود.
- صوت به‌صورت افزایشی در `$BACKUP_DIR/audio-mirror` (دیسک هاست) mirror می‌شود، نه داخل کانتینر. این mirror snapshot نیست و حذف‌های retention را پاک نمی‌کند.
- بدون کلیدهای داخل `secrets.tar.enc` دادهٔ پایگاه‌های مشتریان قابل رمزگشایی نیست. رمز بسته را جدا از خود پشتیبان نگه دارید.
- پاک‌سازی: پشتیبان‌های کامل‌تر از `BACKUP_RETENTION_DAYS` (پیش‌فرض ۱۴) حذف می‌شوند، ولی همیشه `BACKUP_KEEP_LAST` (پیش‌فرض ۷) نسخه‌ی تازه می‌ماند.
- فایل `$BACKUP_DIR/.last_success` زمان آخرین پشتیبان موفق است؛ برای هشدار «پشتیبان قدیمی» از آن استفاده کنید.
- بدون `BACKUP_OFFSITE_TARGET` پشتیبان فقط روی همین هاست است و اسکریپت هشدار می‌دهد.

### بازیابی کامل

```bash
./scripts/restore.sh /srv/backup/20260819T020000Z          # تأیید تعاملی: RESTORE <نام پشتیبان>
./scripts/restore.sh --yes --restore-secrets <backup-dir>  # بدون پرسش؛ .env را در .env.from-backup می‌نویسد
```

ترتیب کار: بررسی checksum و dumpها ← توقف همهٔ writerها (api، asr، emotion، llm، notify، dispatch، provision) ← snapshot پیش از restore در `$BACKUP_DIR/pre-restore` ← restore هر پایگاه در یک پایگاه تازه (`--exit-on-error --single-transaction`) و جابه‌جایی با rename ← اجرای دوبارهٔ نقش و GRANTهای `cbi_app` و مشتریان ← بازگردانی صوت ← راه‌اندازی مجدد سرویس‌ها. اگر هر مرحله‌ی restore خطا بدهد، پایگاه فعلی دست‌نخورده می‌ماند. پایگاه‌های جایگزین‌شده با نام `<db>_pre<stamp>` می‌مانند؛ پس از راستی‌آزمایی با `DROP DATABASE` حذف کنید. برگشت: سرویس‌ها را متوقف و `ALTER DATABASE` معکوس بزنید.

### بازیابی یک مشتری

```bash
./scripts/restore_tenant.sh /srv/backup/<stamp> <tenant-uuid>
```

فقط پایگاه همان مشتری جایگزین می‌شود (همان روش fresh‑DB + rename)، نقش مشتری باید وجود داشته باشد (روی سرور اصلی هست؛ روی سرور بازسازی‌شده از `--roles-file` استفاده کنید). داده‌های نوشته‌شده پس از زمان پشتیبان از دست می‌رود.

### تمرین ماهانهٔ بازیابی (restore drill)

روی یک هاست جدا (نه production) انجام شود:

1. استک را با `.env` خالی/تست بالا بیاورید و `postgres` و `minio` را راه بیندازید.
2. آخرین پشتیبان و `audio-mirror` را از مقصد خارج از هاست کپی کنید و `BACKUP_PASSPHRASE_FILE` را تنظیم کنید.
3. `./scripts/restore.sh --restore-secrets <backup-dir>` را اجرا و زمان آن را ثبت کنید.
4. `.env.from-backup` را با `.env` مقایسه یا جایگزین کنید و `docker compose up -d` بزنید.
5. بررسی: `/healthz`، تعداد تماس‌ها در هر پایگاه در برابر `MANIFEST`، باز شدن یک مشتری نمونه، پخش یک فایل صوتی، ورود با کلید API.
6. نتیجه و RTO را در گزارش ماهانه ثبت کنید؛ شکست تمرین یعنی پشتیبان‌ها معتبر نیستند و باید همان روز رفع شود.

## ظرفیت و بار

هدف: ۳۰۰ ساعت صوت در ۲۴ ساعت روی یک سرور مرجع. برای سنجش:

```bash
uv run python scripts/loadgen.py --base-url https://api.<domain> --api-key sk_live_... \
    --calls 6000 --concurrency 16 --seconds 180
```

معیارهای قابل قبول: صدک ۹۵ زمان ingest زیر ۵ ثانیه، عمق صف بازگشت‌پذیر زیر ۱ ساعت،
نرخ خطای نهایی زیر ۱ درصد.

## چرخش اسرار

`JWT_SECRET` و `API_KEY_PEPPER` را فقط با برنامه‌ی مهاجرت عوض کنید؛ تغییر pepper همه‌ی
کلیدهای API را باطل می‌کند و مشتری باید کلید جدید بسازد. رمز MinIO و Postgres را با
`docker compose up -d --force-recreate` پس از به‌روزرسانی `.env` اعمال کنید.


## ماژول FreePBX: آپدیت امن، کلید امضا و عیب‌یابی

- **کلید امضا**: سرور هر پیشنهاد آپدیت را با یک *manifest* امضاشده (نسخه، sha256، اندازه، کانال، انقضای ۷ روزه) می‌دهد؛ helper ریشه‌ی PBX بدون manifest معتبر نصب نمی‌کند و هر نسخه‌ی غیر جدیدتر را رد می‌کند.
- **چرخش کلید**: فایل `release-signing.pub` روی PBX تا سه کلید (هر کدام یک خط) می‌پذیرد. مراحل: (۱) کلید جدید بسازید و در یک نسخه‌ی منتشرشده با کلید قدیمی، هر دو کلید را داخل `assets/release-signing.pub` بگذارید؛ (۲) پس از رسیدن آن نسخه به ناوگان، `MODULE_RELEASE_SIGNING_KEY` سرور را به کلید جدید تغییر دهید؛ (۳) در نسخه‌ی بعد کلید قدیمی را حذف کنید. کلید خصوصی را همراه backup رمزگذاری‌شده نگه دارید (`scripts/backup.sh`)؛ گم‌شدنش یعنی هیچ PBX آپدیت نمی‌گیرد.
- **گزارش سلامت**: ماژول ۱٫۴ به بالا هر ساعت نتیجه‌ی `doctor.php` را به `/v1/ingest/module/diagnostics` می‌فرستد؛ در ادمین > سرورهای FreePBX > «گزارش سلامت» دیده می‌شود. کدهای `SS-...` به `/help/errors/<کد>` لینک می‌شوند.
- **هشدارها**: Alertmanager در compose هست (`deploy/alertmanager/alertmanager.yml`)؛ برای دریافت واقعی هشدار یک receiver (webhook/ایمیل) در آن فایل تنظیم کنید.
- **بازگرداندن ضبط‌های failed**: روی PBX `php /usr/local/bin/asterisk-recording-uploader/bin/requeue-failed.php` (با `--dry-run` یا `--code=SS-...`).
