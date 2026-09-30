# راهنمای عملیات (Runbook)

## سلامت روزانه

- `GET /healthz` سبک است؛ `GET /readyz` وضعیت Postgres، Redis، MinIO و llama-server را می‌دهد.
- داشبورد Grafana «Pipeline»: نرخ ingest، عمق صف، صدک ۹۵ انتظار کار، خطای JSON مدل، پاسخ وب‌هوک.
- هشدارهای Prometheus در `deploy/prometheus/alerts.yml`.

## عیب‌یابی

| نشانه | بررسی | اقدام |
| --- | --- | --- |
| صف ASR رشد می‌کند | `docker compose logs worker-asr` | افزایش `--workers` یا replica ورکر ASR |
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
BACKUP_DIR=/srv/backup ./scripts/backup.sh          # pg_dump + mirror MinIO
./scripts/restore.sh /srv/backup/20260819T020000Z    # تمرین بازیابی
```

تمرین بازیابی را ماهانه روی یک محیط جدا اجرا کنید و زمان بازگشت را ثبت کنید.

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
