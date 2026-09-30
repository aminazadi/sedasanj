# پلن جامع بازبینی دوم و رفع نقص‌ها

بازبینی کامل کدبیس در برابر مشخصات فنی (§۲ تا §۱۵) بعد از مرج PR #1.
هیچ تست end-to-end اجرا نشده است؛ اعتبارسنجی فقط static/unit است.

شدت‌ها: **C** بحرانی، **H** بالا، **M** متوسط.

## C — نقص‌های بحرانی

| # | نقص | شاهد | رفع |
|---|-----|------|-----|
| C1 | نام برچسب متریک‌ها با محل مصرف نمی‌خواند؛ هر تحویل webhook و هر خطای JSON مدل با `ValueError` می‌شکند | `metrics.py` (`webhook_responses_total` با برچسب `class`، `llm_json_failures_total` با برچسب `stage`) در برابر `worker_notify/main.py` و `worker_llm/main.py` | هم‌نام‌سازی برچسب‌ها (`status`, `stage`) و پاس دادن مقدار در همه‌ی محل‌ها |
| C2 | شکست webhook وضعیت خود تماس را به `failed_*` می‌برد و بعد از پایان تلاش‌ها رویداد `call.failed` صف می‌شود → تماس سالم خراب و حلقه‌ی اعلان | `pipeline.handle_failure` + `worker_notify.deliver_event` | شکست `notify` فقط job را علامت می‌زند؛ dead-letter در `webhook_deliveries` ثبت می‌شود و اعلان مجدد صف نمی‌شود |
| C3 | `asterisk_uniqueid` با `Idempotency-Key` جایگزین می‌شد و درخواست‌های همزمان تکراری به خطای یکتایی/۵۰۰ می‌خورد | `routers/ingest.py` | ذخیره‌ی همیشگی uniqueid واقعی، بازپخش بر اساس uniqueid، مهار `IntegrityError` → پاسخ ۲۰۰ بازپخش |
| C4 | حذف داده‌ی مستأجر بدون فیلتر `tenant_id` و تنها با تکیه بر RLS اجرا می‌شد | `routers/account.py::delete_tenant_data` | فیلتر صریح `tenant_id` روی همه‌ی DELETE/UPDATE (defense in depth) |
| C5 | اتصال اپ با نقش superuser دیتابیس بود؛ superuser از RLS (حتی FORCE) عبور می‌کند → جداسازی مستأجر عملاً غیرفعال | `deploy/compose.yml` (`POSTGRES_USER: cbi`) + `0001_baseline` | نقش غیرsuperuser `cbi_app` در init دیتابیس؛ API/ورکرها با آن وصل می‌شوند، مالک اسکیما فقط برای `migrate` می‌ماند و `assert_rls_enforced` در استارتاپ اجرای production را با نقش عبورکننده از RLS متوقف می‌کند |
| C6 | `reanalyze` برای تماس‌های تمام‌شده بی‌اثر بود (claim وضعیت `complete` را نمی‌پذیرفت) | `routers/calls.py` + `worker_llm/main.py` | مسیر reanalyze با پرچم صریح، پذیرش وضعیت‌های نهایی، بازگردانی وضعیت قبلی، بدون شارژ و بدون اعلان تکراری |
| C7 | لینک presigned صوت به آدرس داخلی `minio:9000` می‌خورد و از مرورگر قابل دریافت نبود | `services/storage.py` | تنظیم `MINIO_PUBLIC_ENDPOINT` برای امضا + انتشار محدود پورت MinIO و پراکسی `AUDIO_DOMAIN` در Nginx Proxy Manager |
| C8 | webhook فقط در زمان ثبت اعتبارسنجی می‌شد؛ تغییر DNS بعد از ثبت (rebinding) مسیر SSRF را باز می‌گذاشت | `worker_notify/main.py` | اعتبارسنجی مجدد در لحظه‌ی ارسال + غیرفعال‌کردن redirect |

## H — نقص‌های مهم

| # | نقص | رفع |
|---|-----|-----|
| H1 | هم `handle_failure` و هم خود ورکرها کار را دوباره صف می‌کردند → هر شکست دو تلاش تولید می‌کرد | زمان‌بندی retry فقط در `pipeline.handle_failure` متمرکز شد و ورکرها نتیجه‌ی رشته‌ای برمی‌گردانند |
| H2 | آدرس webhook اعتبارسنجی نمی‌شد (SSRF به شبکه‌ی داخلی) | اعتبارسنجی طرح و مسدودسازی loopback/private/link-local |
| H3 | حذف webhook با تحویل‌های ثبت‌شده به خطای FK می‌خورد | `ON DELETE CASCADE` در مهاجرت ۰۰۰۲ |
| H4 | ورود کاربر با ایمیل تکراری در دو مستأجر خطای ۵۰۰ می‌داد | تطبیق رمز روی همه‌ی کاربران آن ایمیل |
| H5 | `totp_code` دریافت می‌شد ولی هرگز بررسی نمی‌شد | پیاده‌سازی TOTP (RFC 6238) و الزام آن برای کاربران دارای `totp_secret` |
| H6 | CORS با `https?://.*` و `allow_credentials` | لیست مبدأهای مجاز از تنظیمات |
| H7 | `/metrics` عمومی بود و متریک ورکرها اصلاً scrape نمی‌شد | الزام `METRICS_TOKEN` در API + سرور متریک داخلی ورکر و scrape جدید |
| H8 | `monthly_minute_quota` و `max_concurrent_jobs` هیچ‌جا اعمال نمی‌شد | سهمیه‌ی ماهانه در ingest (`quota_exceeded`) و کنترل هم‌زمانی در ورکر ASR |
| H9 | رویداد `balance.low` هرگز تولید نمی‌شد | تولید پس از settle با آستانه و قفل روزانه + ارسال webhook علاوه بر ایمیل |
| H10 | نقش‌های staff تفکیک نشده بود (support = super_admin) | محدودسازی ساخت/ویرایش مستأجر، پکیج و تنظیمات به `super_admin` |
| H11 | آلارم/متریک ناقص: `failed_retryable`، دیسک، `job_wait_seconds` | گیج `cbi_jobs_failed_retryable`، node-exporter و آلارم دیسک، ثبت زمان انتظار job |
| H12 | حجم آپلود با عدد ثابت در کد محدود می‌شد | `MAX_UPLOAD_BYTES` در تنظیمات |

## M — بهبودهای متوسط

| # | نقص | رفع |
|---|-----|-----|
| M1 | API می‌توانست قبل از اتمام مهاجرت بالا بیاید | `depends_on: migrate: service_completed_successfully` |
| M2 | مقادیر پیش‌فرض «change-me» برای رمزها در محیط production | اعتبارسنجی fail-fast در تنظیمات |
| M3 | ورودی‌های spool پس از اتمام تلاش‌ها حذف می‌شد | انتقال به پوشه‌ی `failed/` |
| M4 | نبود فیلتر مستأجر در حذف کاربر و نبود `active` در `PackageOut` | اضافه شد |
| M5 | reconciler وضعیت `notified` و job های `failed_retryable` سرِ موعد را نمی‌دید | اضافه شد |
| M6 | مهاجرت ۰۰۰۲ روی مقدار وضعیت اشتباه (`open`) ایندکس یکتا می‌ساخت و ایندکس job تکراری بود | ایندکس روی `held` و حذف ایندکس تکراری |
| M7 | اعتبارسنجی SSRF نام‌گشایی مسدودکننده را داخل event loop اجرا می‌کرد | نسخه‌ی async با `asyncio.to_thread` |

## اعتبارسنجی

- `ruff check` / `ruff format --check`
- `mypy apps`
- `pytest` (تست‌های واحد جدید برای C1..C7 و H1..H9)
- `python -m compileall apps tests scripts`
- `tsc --noEmit` و build هر دو پنل
- بررسی نحوی YAML/JSON/TOML/shell، `docker compose config` و `nginx -t`

خارج از دامنه (طبق درخواست کاربر): هیچ تست end-to-end، هیچ اجرای واقعی Shenava/Dorna، هیچ تماس واقعی Asterisk.
