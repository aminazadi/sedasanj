# استقرار روی Ubuntu 24.04

## پیش‌نیاز سخت‌افزار

**با VoiceSanj (ASR/LLM ریموت):** حداقل ۴ هسته و ۸ گیگ RAM کافی است؛ سرویس‌های
`llm1`/`llm2` به‌صورت پیش‌فرض بالا نمی‌آیند.

**با مدل محلی (Dorna روی CPU):** CPU با AVX2 و حداقل ۱۶ هسته، ۶۴ گیگابایت RAM
(۲ نمونه llama-server)، و SSD با حداقل ۵۰۰ گیگابایت. در `.env` مقدار
`COMPOSE_PROFILES=local-llm` را بگذارید و محدودیت‌های `LLM_CPUS` / `LLM_MEMORY` را
با سخت‌افزار هماهنگ کنید.

## گام‌ها

```bash
sudo apt update && sudo apt install -y docker.io docker-compose-v2 ffmpeg
sudo mkdir -p /srv/models /srv/backup
# مدل‌ها را در /srv/models قرار دهید:
#   dorna-llama3-8b-instruct-q4_k_m.gguf
#   shenava-koochik-int8.bin
git clone https://github.com/aminazadi/cbi-voice-analytics.git /srv/cbi
cd /srv/cbi/deploy
cp .env.example .env && ${EDITOR:-nano} .env      # همه رمزها و تنظیمات شبکه را پر کنید
docker compose config --quiet
docker compose up -d --build --remove-orphans
docker compose logs -f migrate
```

در `.env` این دو مقدار اجباری‌اند:

- `PUBLISH_ADDRESS`: آدرس IP متعلق به همین VPS که سرور Nginx Proxy Manager می‌تواند به آن برسد.
  از `0.0.0.0` استفاده نکنید. اگر بین دو VPS شبکه خصوصی یا WireGuard دارید، IP همان شبکه بهترین گزینه است.
- `NPM_PROXY_IP`: آدرس مبدأ اتصال‌های Nginx Proxy Manager به این VPS. Uvicorn فقط هدرهای
  `X-Forwarded-*` رسیده از این IP و شبکه داخلی اختصاصی `APP_PROXY_SUBNET` را معتبر می‌داند.

پورت‌های production به‌صورت پیش‌فرض چنین‌اند:

| مقصد | پورت VPS | کاربرد |
| --- | ---: | --- |
| `client` | 3000 | پنل مشتری و proxy داخلی مسیر `/v1/` به API |
| `admin` | 3001 | پنل کارکنان و proxy داخلی مسیر `/v1/` به API |
| `api` | 8000 | API عمومی برای agentها و یکپارچه‌سازی‌ها |
| `minio` | 9000 | لینک‌های کوتاه‌عمر فایل صوتی |
| `grafana` | 3002 | داشبورد عملیاتی |

PostgreSQL، Redis، Prometheus، Loki، workerها، llama-serverها، node-exporter و کنسول مدیریتی
MinIO روی پورت 9001 هیچ port mapping عمومی ندارند.

نکته امنیتی: API و ورکرها با نقش `cbi_app` (بدون superuser) به Postgres وصل می‌شوند تا سیاست‌های RLS
واقعاً اعمال شود؛ این نقش در اولین راه‌اندازی از `deploy/postgres/init/10-app-role.sh` با
`APP_DB_PASSWORD` ساخته می‌شود و فقط سرویس `migrate` با نقش مالک (`cbi`) اجرا می‌شود. اگر Postgres
از قبل راه‌اندازی شده بود، این اسکریپت را یک بار دستی اجرا کنید:

```bash
docker compose exec -e APP_DB_PASSWORD="$APP_DB_PASSWORD" postgres \
  sh /docker-entrypoint-initdb.d/10-app-role.sh
```

`METRICS_TOKEN` نیز `/metrics` را می‌بندد و Prometheus با همان توکن از شبکه داخلی scrape می‌کند.

## تنظیم Nginx Proxy Manager

رکوردهای DNS مربوط به `API_DOMAIN`، `APP_DOMAIN`، `ADMIN_DOMAIN`، `AUDIO_DOMAIN` و
`GRAFANA_DOMAIN` باید به IP عمومی سرور Nginx Proxy Manager اشاره کنند، نه IP این VPS.

در NPM پنج Proxy Host بسازید. Scheme همه مقصدها `http` و Forward Hostname همان
`PUBLISH_ADDRESS` است:

| Domain | Forward port | SSL |
| --- | ---: | --- |
| `API_DOMAIN` | 8000 | Force SSL + HTTP/2 |
| `APP_DOMAIN` | 3000 | Force SSL + HTTP/2 |
| `ADMIN_DOMAIN` | 3001 | Force SSL + HTTP/2 |
| `AUDIO_DOMAIN` | 9000 | Force SSL + HTTP/2 |
| `GRAFANA_DOMAIN` | 3002 | Force SSL + HTTP/2 + WebSocket Support |

برای میزبان‌های API و پنل مشتری، بخش Advanced را با این مقادیر تنظیم کنید تا آپلود WAV بزرگ
در NPM متوقف یا buffer نشود. مقدار `MAX_UPLOAD_BYTES` در `.env` نیز باید با این سقف هماهنگ باشد:

```nginx
client_max_body_size 512m;
proxy_request_buffering off;
proxy_read_timeout 3600s;
proxy_send_timeout 3600s;
```

برای `AUDIO_DOMAIN` در بخش Advanced، Host عمومی را حفظ و buffering را غیرفعال کنید تا امضای
لینک MinIO و دانلود فایل بدون تغییر باقی بماند:

```nginx
proxy_http_version 1.1;
proxy_set_header Host $http_host;
proxy_buffering off;
proxy_request_buffering off;
```

گواهی TLS در NPM صادر می‌شود. گزینه‌های `Block Common Exploits` و `Force SSL` را فعال کنید؛
برای `AUDIO_DOMAIN` هیچ access-list مبتنی بر login نگذارید، چون دسترسی فایل با امضای کوتاه‌عمر
MinIO کنترل می‌شود.

## محدودسازی شبکه

در فایروال ارائه‌دهنده VPS یا security group، پورت‌های `3000`، `3001`، `3002`، `8000` و
`9000/TCP` را فقط برای `NPM_PROXY_IP` مجاز کنید. SSH را پیش از تغییر قواعد جداگانه مجاز نگه دارید.
صرفاً تنظیم UFW همیشه برای پورت‌های publish‌شده Docker کافی نیست؛ اگر فایروال بالادستی ندارید،
قواعد معادل را در زنجیره `DOCKER-USER` اعمال و ماندگار کنید. قبل و بعد از اعمال قواعد، اتصال SSH
جداگانه و دسترسی NPM را آزمایش کنید.

سپس اولین مشتری و کاربر کارکنان را بسازید. با `SEED_*` در `.env` سرویس
`seed` هنگام `docker compose up` خودش حساب‌های نبوده را می‌سازد.

برای اجرای دستی:

```bash
docker compose run --rm seed
```

برای اجبار به ست‌کردن مجدد رمزها یک‌بار `SEED_RESET_PASSWORDS=true` بگذارید، compose را
بالا بیاورید، بعد دوباره `false` کنید.

پنل کارکنان: `https://admin.<domain>` با `/v1/admin/auth/login`  
پنل مشتری: `https://app.<domain>` با `/v1/auth/login`

توجه: `SEED_API_KEY` فقط با همان `API_KEY_PEPPER` کار می‌کند که موقع seed استفاده شده؛
pepper را عوض نکنید.

## سرویس‌ها

| سرویس | نقش | پورت داخلی |
| --- | --- | --- |
| client / admin | سرو استاتیک پنل‌ها و proxy مسیر `/v1/` | 80 ← پورت‌های 3000/3001 VPS |
| api | FastAPI | 8000 |
| migrate | اجرای Alembic و خروج | — |
| worker-asr / worker-emotion / worker-llm / worker-notify / worker-dispatch | ورکرهای ARQ و تحویل پایدار صف | — |
| llm1 / llm2 | llama-server روی مدل Dorna (پروفایل `local-llm`) | 8081 |
| postgres / redis / minio | داده، صف، آبجکت استوریج | 5432 / 6379 / 9000؛ فقط MinIO روی VPS publish است |
| prometheus / grafana / loki / promtail / node-exporter | مشاهده‌پذیری | فقط Grafana روی پورت 3002 VPS publish است |

## حذف نویز و بهبود کیفیت صوت

این مرحله در `worker-asr` و پیش از ارسال صوت به مدل ASR اجرا می‌شود. برای صوت استریو، کانال
مشتری و کارشناس جداگانه پردازش می‌شوند و سپس هر WAV نهایی با مشخصات mono، 16 kHz و PCM16 از
طریق مسیر انتخاب‌شده در پنل به AISERVICE ارسال می‌شود. WAV همیشه با gzip قطعی،
`audio_encoding=gzip`، نوع `application/gzip` و اندازۀ اصلی صوت ارسال می‌شود. هیچ فیلد اختصاصی
یا مستندنشدۀ denoiser به سرویس فرستاده نمی‌شود.

تنظیم اصلی از صفحه «تنظیمات مدل‌ها» در پنل کارکنان انجام می‌شود و در `platform_settings` ذخیره
می‌گردد. مقادیر `.env` فقط fallback اولیه هستند:

```dotenv
AUDIO_PREPROCESSING_ENABLED=false
AUDIO_DENOISER_MODEL=speech-afftdn-balanced
AUDIO_ENHANCEMENT_MODEL=speech-clarity-balanced
```

پروفایل‌های `balanced` برای شروع پیشنهاد می‌شوند. حالت `strong` را فقط پس از مقایسه روی چند
نمونۀ واقعی پرنویز فعال کنید، چون پردازش شدید می‌تواند بخش‌هایی از گفتار ضعیف را نیز کاهش دهد.
نسخۀ اعمال‌شده همراه با `asr_version` متن ذخیره می‌شود تا نتیجۀ هر تماس قابل ردیابی باشد.

## تحلیل لحن روی CPU

`worker-emotion` پس از ASR و پیش از تحلیل متن اجرا می‌شود. کانال مشتری و اپراتور را مستقل، بر
اساس زمان‌بندی utteranceها، به پنجره‌های محدود تقسیم می‌کند و emotion2vec+ base را فقط روی CPU
اجرا می‌کند. شناسه و revision مدل همراه پروفایل صوت ذخیره می‌شود. مدل در نخستین اجرای واقعی در
volume پایدار `emotion-model-cache` دریافت و برای راه‌اندازی‌های بعدی استفاده می‌شود.

```dotenv
VOICE_SENTIMENT_ENABLED=true
VOICE_SENTIMENT_MODEL=iic/emotion2vec_plus_base
VOICE_SENTIMENT_MODEL_REVISION=b318240bfe67db81a8c572ecb37ce9c3759b81c9
VOICE_SENTIMENT_HUB=hf
VOICE_SENTIMENT_CPU_THREADS=2
VOICE_SENTIMENT_WINDOW_SECONDS=8
VOICE_SENTIMENT_MIN_SECONDS=1
VOICE_SENTIMENT_MAX_WINDOWS=720
VOICE_SENTIMENT_TIMEOUT_SECONDS=900
MAX_CONCURRENT_EMOTION_JOBS=1
TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu
```

revision پیش‌فرض به نسخۀ اصلاح‌شدۀ رسمی مدل pin شده است. تغییر مدل یا revision ابتدا باید روی
نمونه‌های تماس فارسی ارزیابی شود. مجوز وزن‌های FunASR الزام انتساب منبع و حفظ نام مدل را دارد؛
پیش از انتشار تجاری متن جاری `MODEL_LICENSE` نیز بازبینی شود. اگر مدل پس از سه تلاش در دسترس
نباشد، job با وضعیت نهایی ثبت می‌شود ولی تماس به‌صورت degraded وارد تحلیل متن می‌شود.

## قرارداد پردازش AISERVICE و اتصال مستقیم 9Router

- اتصال AISERVICE و اتصال مستقیم 9Router مستقل هستند. مسیر ASR، تحلیل، دستیار،
  تصمیم‌گیری و embedding در تب مدل‌ها و مسیر تصحیح متن در تب تصحیح انتخاب می‌شود.
  انتخاب 9Router مستقیم به کلید AISERVICE نیاز ندارد.
- آدرس پایه را به صورت `https://domain` یا `http://ip:port` وارد کنید؛ مسیرهای `/v1/...`
  را برنامه اضافه می‌کند. در Docker، `127.0.0.1` به همان کانتینر اشاره می‌کند؛ آدرس 9Router
  باید از API و workerها قابل دسترسی باشد.
- پیش از ذخیرهٔ کلید مستقیم، `PLATFORM_SECRETS_KEY` را یک‌بار با فرمان زیر بسازید و
  مقدار یکسان و پایدار آن را در محیط API و workerها قرار دهید. Compose این مقدار را از
  فایل محیط دریافت می‌کند؛ پس از تنظیم، سرویس‌های مربوط را بازسازی کنید. این کلید باید
  همراه پشتیبان تنظیمات نگهداری شود و نباید در هر راه‌اندازی دوباره تولید شود.

  ```sh
  python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
  ```

- آدرس، API key، timeout، مدل و پرامپت هر قابلیت از تنظیمات ادمین مدیریت می‌شوند.
  آزمایش اتصال و دریافت مدل‌ها با مقادیر واردشده پیش از ذخیره امکان‌پذیر است؛ این عملیات
  تنظیمات را تغییر نمی‌دهد. خالی‌گذاشتن API key کلید ذخیره‌شده را حفظ می‌کند.
- اتصال مستقیم از `/v1/audio/transcriptions`، `/v1/chat/completions` و `/v1/embeddings`
  استفاده می‌کند. تصمیم‌گیری و تصحیح متن، پاسخ ساختاریافتهٔ Chat را اعتبارسنجی می‌کنند.
  شکست مسیر مستقیم باعث انتقال خودکار درخواست به AISERVICE نمی‌شود.
- تصحیح خودکار طبق تنظیمات تصحیح متن اجرا می‌شود و نسخه‌ها و timestampهای متن حفظ
  می‌شوند. قرارداد صف پایدار و endpointهای زیر مربوط به مسیر AISERVICE است.
- endpoint مستند `POST /v1/text/process` فقط عملیات `correction` و `minutes` را می‌پذیرد؛
  استخراج JSON اختصاصی تحلیل تماس از آن قابل درخواست نیست.
- استخراج اختصاصی با `POST /v1/chat/tasks` ثبت می‌شود، وضعیت از
  `GET /v1/tasks/{task_id}` و خروجی نهایی از `GET /v1/tasks/{task_id}/result` دریافت می‌شود.
  درخواست استریم نیست؛ شناسه تکرارپذیر مبتنی بر اجرای تحلیل و محتوای درخواست از ثبت تکراری
  همان کار در تلاش‌های مجدد جلوگیری می‌کند. مهلت polling از حداقل
  `VOICESANJ_POLL_TIMEOUT_SECONDS` و `ANALYSIS_TIMEOUT_SECONDS - 30` به دست می‌آید.
- تحویل بین مراحل از جدول پایدار `job_outbox` انجام می‌شود. PostgreSQL منبع حقیقت است و
  قطع موقت Redis باعث گم‌شدن کار نمی‌شود. درخواست‌های VoiceSanj پس از ثبت، با jobهای کوتاه
  و زمان‌بندی‌شده پیگیری می‌شوند تا worker هنگام انتظار provider اشغال نماند.

## پس از استقرار

1. `curl -fsS https://api.<domain>/healthz` و `/readyz`
2. ورود به `https://admin.<domain>` و ساخت مشتری
3. نصب `cbi-agent` روی سرور Asterisk (<../apps/agent/README.md>)
4. فعال‌سازی پشتیبان‌گیری شبانه:
   ```
   0 2 * * * cd /srv/cbi/deploy && BACKUP_DIR=/srv/backup /srv/cbi/scripts/backup.sh >> /var/log/cbi-backup.log 2>&1
   ```
5. تعریف داشبورد Grafana (`pipeline.json` به‌صورت خودکار provision می‌شود) و بررسی هشدارها.

اگر این استقرار قبلاً با reverse proxy داخلی اجرا شده است، `--remove-orphans` کانتینر قدیمی را
حذف می‌کند. پس از اطمینان از کارکرد NPM، volumeهای گواهی قدیمی را با بررسی نام دقیق در
`docker volume ls` حذف کنید؛ این volumeها دیگر توسط Compose تعریف یا استفاده نمی‌شوند.
