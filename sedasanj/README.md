# CBI Voice Analytics

سامانه‌ی چندمستأجری تحلیل پس از تماس برای مشتریان Asterisk: صوت ضبط‌شده را می‌گیرد،
با Shenava-Koochik به فارسی پیاده می‌کند، با Dorna تحلیل ساختاریافته می‌سازد،
اعتبار مشتری را محاسبه می‌کند و نتیجه را در پنل و وب‌هوک تحویل می‌دهد.

## اجزا

| مسیر | نقش |
| --- | --- |
| `apps/api` | FastAPI: احراز هویت، ingest، تماس‌ها، تحلیل‌ها، صورتحساب، وب‌هوک، پنل مدیریت |
| `apps/worker_asr` | ورکر ARQ برای پیاده‌سازی صوت (کانال چپ = مشتری، راست = اپراتور) |
| `apps/worker_emotion` | تحلیل لحن هر کانال با emotion2vec+ base روی CPU |
| `apps/worker_llm` | ورکر ARQ برای استخراج JSON با llama-server |
| `apps/worker_dispatch` | تحویل پایدار jobهای دیتابیس به صف Redis |
| `apps/worker_notify` | ورکر ARQ برای وب‌هوک امضاشده و ایمیل |
| `apps/agent` | `cbi-agent`، سرویس سبک کنار Asterisk (AMI + آپلود با صف روی دیسک) |
| `web/client` | پنل مشتری (React + TS + Tailwind، RTL) |
| `web/admin` | پنل کارکنان پلتفرم |
| `deploy` | Docker Compose، سرو فرانت با Nginx، Prometheus، Grafana، Loki |
| `scripts` | seed، پشتیبان‌گیری، بازیابی، تولید بار |

## خط لوله

```
received → reserved → stored → transcribing → emotion_queued
        → emotion_analyzing → transcribed → analyzing
        → analyzed → billed → notified → complete
```

خطاها: `failed_retryable`، `failed_terminal`، `canceled`. سیاست تلاش مجدد:
ASR ۵ تلاش/۵ ثانیه، تحلیل لحن ۳ تلاش/۱۰ ثانیه، LLM ۴ تلاش/۱۰ ثانیه و
اطلاع‌رسانی ۸ تلاش/۱۵ ثانیه (ضریب ۲). شکست نهایی تحلیل لحن مسیر تحلیل متن را متوقف نمی‌کند.

## قواعد کلیدی

- ورودی agent بر اساس تنظیم هر API key، GZIP یا ZIP (با رمز اختیاری AES-256) است؛
  کلیدهای قدیمی WAV را برای سازگاری می‌پذیرند. محتوای استخراج‌شده باید WAV با PCM خطی،
  ۸ یا ۱۶ کیلوهرتز و ۱ یا ۲ کانال باشد.
- فایل اصلی دست‌نخورده در MinIO می‌ماند؛ تبدیل به ۱۶ کیلوهرتز فقط در فضای کار ورکر انجام می‌شود.
- کلید آبجکت: `{tenant_id}/{call_id}.wav` — هیچ شماره تلفنی در نام فایل نیست.
- ثانیه‌ی محاسبه‌شده: `max(30, ceil(duration_ms / 1000))`؛ رزرو قبل از ذخیره‌سازی و
  تسویه/آزادسازی دقیقاً یک بار با کلیدهای `reserve:`، `settle:`، `release:`.
- امضای وب‌هوک: `X-CBI-Signature: sha256=HMAC(secret, "{ts}.{body}")` با هدر `X-CBI-Timestamp`؛
  دریافت‌کننده باید مهر زمانی قدیمی‌تر از ۵ دقیقه را رد کند.

## توسعه محلی

```bash
uv venv --python 3.12 && uv pip install -e ".[dev]"
docker compose -f deploy/compose.local.yml up -d
alembic -c apps/api/alembic.ini upgrade head
uv run python scripts/seed.py --minutes 600
uvicorn app.main:app --app-dir apps/api --reload
```

پنل‌ها:

```bash
cd web/client && npm install && npm run dev   # 5173
cd web/admin  && npm install && npm run dev   # 5174
```

مستندات API مشتری پس از ورود از مسیر `/api-docs` پنل و schema خام از
`/v1/openapi/customer.json` در دسترس است.

بررسی‌های کیفیت:

```bash
ruff check . && ruff format --check .
mypy apps
pytest
(cd web/client && npm run build) && (cd web/admin && npm run build)
```

## استقرار

راهنمای کامل نصب روی Ubuntu 24.04 در <docs/deployment.md> و عملیات روز-دوم در
<docs/runbook.md> آمده است. راه‌اندازی سمت Asterisk در <apps/agent/README.md>.
