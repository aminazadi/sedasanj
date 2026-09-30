# Persian ASR Service

سرویس چندمدلی تبدیل گفتار فارسی به متن با پنل مدیریت، دانلود قابل ادامه و آمار مصرف.
هیچ مدل هوش مصنوعی هنگام `docker build` یا startup دانلود نمی‌شود.

## اجرا

```bash
cp .env.example .env
# مقدار ASR_API_KEY را در .env تنظیم کنید
docker compose up -d --build
```

برای شبکه‌هایی که دسترسی به PyPI محدود است، build به‌صورت پیش‌فرض از mirror دانشگاه
Tsinghua استفاده می‌کند. منبع از `.env` قابل تغییر است:

```env
PIP_INDEX_URL=https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple
PIP_DEFAULT_TIMEOUT=600
```

گزینه جایگزین:

```env
PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
```

بعد از تغییر mirror، `docker compose build --no-cache` را اجرا کنید. مقدار
`PIP_EXTRA_INDEX_URL` عمداً خالی است تا pip مجدداً سراغ PyPI محدودشده نرود.

نسخه `sherpa-onnx` روی `1.12.39` ثابت شده است؛ این نسخه برای Python 3.11 و Linux
x86_64/ARM64 wheel آماده دارد و روی mirror نیز موجود است.

پنل در `http://localhost:8000/admin` است. کلید واردشده فقط در `sessionStorage`
مرورگر نگهداری و برای API به شکل Bearer token ارسال می‌شود. داده‌ها، مدل‌ها، فایل‌های
`.part` و SQLite در volume پایدار `asr-data` ذخیره می‌شوند.

پنل نصب، pause/ادامه، پیشرفت، سرعت، خطا، انتخاب مدل، نمودار ۱۴ روزه و جدول صفحه‌بندی‌شده
درخواست‌ها را نمایش می‌دهد. دانلودر از HTTP Range، retry با backoff، بازیابی پس از restart،
اعتبارسنجی اندازه‌های قطعی، SHA-256 manifest و فعال‌سازی اتمی bundle پشتیبانی می‌کند.

در بخش «پراکسی دانلود Hugging Face» می‌توان میزبان، پورت و اطلاعات ورود SOCKS5H را
تنظیم کرد. گزینه «ذخیره و تست» اتصال واقعی به Hugging Face، زمان پاسخ، HTTP status،
زمان آخرین بررسی و استفاده از DNS سمت پراکسی را نشان می‌دهد. رمز در پاسخ API یا پنل
بازگردانده نمی‌شود. پس از تغییر وابستگی‌ها image را دوباره build کنید.

## مدل‌ها

- Silero VAD (برای Shenava اجباری)
- GTCRN denoiser (اختیاری)
- Shenava Koochik CTC و RNNT
- Shenava Rizeh و Rizeh-Pizeh CTC
- Faster Whisper Large v3
- Whisper Persian v4 (CTranslate2 INT8)
- BuzzASR Persian با tokenizer اختصاصی (CTranslate2 INT8)
- Dorna Llama3 8B در سه نسخه Q4_K_M، Q3_K_M و Q2_K

شناسه دقیق مدل در پنل و `GET /api/models` دیده می‌شود. مدل‌های CTC و RNNT با نقش‌های
صحیح فایل به sherpa-onnx داده می‌شوند. مدل‌ها به‌صورت lazy و تنها هنگام اولین درخواست load
می‌شوند؛ cache بارگذاری نیز حداکثر دو مدل را در RAM نگه می‌دارد. تمام مدل‌های نصب‌شده
همیشه قابل درخواست‌اند و مدل هر کار باید در همان درخواست مشخص شود. خارج شدن یک مدل از
cache فقط RAM را آزاد می‌کند و آن مدل را غیرفعال نمی‌کند.

وزن‌های Whisper Persian v4 و BuzzASR با revision ثابت و SHA-256 رسمی دریافت و هنگام نصب
به CTranslate2 INT8 تبدیل می‌شوند. فایل‌های pickle آموزشی دانلود نمی‌شوند. نصب تنها پس از
تطبیق tokenizer، بررسی artifact و load شدن موفق مدل به شکل اتمی کامل اعلام می‌شود. برای
تبدیل امن حداقل ۴۰GB فضای آزاد و ۳۲GB RAM برای کانتینر توصیه می‌شود.

## صف پایدار و API غیرهمگام

رونویسی صوت و پردازش متن به‌صورت مستقیم در چرخه درخواست HTTP اجرا نمی‌شوند. ورودی صوت
ابتدا در volume پایدار spool و سپس رکورد تسک و سابقه مصرف در یک transaction اتمیک ثبت
می‌شود. API با وضعیت `202 Accepted`، هدرهای `Location` و `Retry-After` و یک شناسه تصادفی
۱۲۸ بیتی پاسخ می‌دهد. workerها فقط به اندازه ظرفیت تنظیم‌شده کار claim می‌کنند؛ در نتیجه
موج درخواست باعث اجرای بی‌حد مدل‌ها و اشباع CPU/RAM نمی‌شود.

وضعیت‌های ممکن: `queued`، `running`، `retrying`، `succeeded`، `failed` و `cancelled`.
صف از SQLite در حالت WAL استفاده می‌کند، claim تسک با `BEGIN IMMEDIATE` اتمیک است، خطاها
با backoff و jitter دوباره امتحان می‌شوند و lease تسک‌های نیمه‌کاره پس از restart بازیابی
می‌شود. فایل ورودی پس از پایان حذف و نتیجه‌ها طبق TTL پاک می‌شوند.

تنظیمات مهم:

- `ASR_TASK_WORKERS`: تعداد workerهای صف پایدار.
- `ASR_LLM_MAX_CONCURRENT`: سقف سراسری contextهای مستقل llama.cpp (پیش‌فرض `2`). context بیکار یک مدل هنگام نیاز مدل دیگر تخلیه می‌شود تا مجموع نسخه‌های مقیم RAM از این سقف عبور نکند.
- `ASR_MAX_CONCURRENT`: سقف مشترک inference برای صف و Chat Completions؛ افزایش آن throughput را بیشتر ولی RAM هر مدل را نیز بیشتر مصرف می‌کند.
- مقدار `0` برای `ASR_MAX_CONCURRENT` و `ASR_TASK_WORKERS` سقف را از CPU محاسبه می‌کند. scheduler از `ASR_INITIAL_CONCURRENT` (پیش‌فرض `1`) شروع می‌کند، در وضعیت سالم تدریجی بالا می‌رود و هنگام عبور CPU/RAM از آستانه یا مشاهدهٔ Linux PSI کاهش می‌یابد.
- `ASR_ADMISSION_CPU_PERCENT` و `ASR_ADMISSION_MEMORY_PERCENT`: آستانهٔ توقف شروع job جدید (پیش‌فرض هر دو `80`). jobهای در حال اجرا قطع نمی‌شوند.
- `ASR_MIN_THREADS_PER_JOB`: حداقل سهم thread هر ASR موازی در محاسبهٔ سقف خودکار (پیش‌فرض `4`).
- `ASR_AUTO_MAX_CONCURRENT`: سقف ایمنی حالت خودکار (پیش‌فرض `8`)؛ سقف واقعی می‌تواند بر اساس CPU و حداقل thread هر job کمتر باشد.
- `ASR_CPU_THREADS`: سقف threadهای داخلی هر inference؛ مقدار `0` آن را از CPU affinity و سهمیه cgroup محاسبه می‌کند و مقدار صریح نیز برای جلوگیری از oversubscription محدود می‌شود.
- `ASR_CPU_BUDGET_PERCENT`: بودجهٔ threadهای native inference بر حسب درصد CPU قابل مشاهده؛ پیش‌فرض `90` است.
- `ASR_WHISPER_BEAM_SIZE`: beam پیش‌فرض Whisper (پیش‌فرض `2`)؛ مقدار `1` سریع‌تر است و `5` برای دقت بیشتر، اما روی CPU بسیار پرهزینه‌تر است.
- `ASR_WHISPER_TEMPERATURE`: دمای decoding Whisper (پیش‌فرض `0`)؛ از temperature fallback چندمرحله‌ای و کند در فایل‌های دشوار جلوگیری می‌کند.
- `ASR_ENABLE_DENOISER`: به‌صورت پیش‌فرض `0` است. با مقدار `1`، GTCRN فقط پس از شکست فایل اصلی با VAD روشن و خاموش اجرا می‌شود؛ هیچ‌گاه جایگزین بی‌قیدوشرط فایل اصلی نیست. اگر هر دو مسیر segment ندهند، task با خطای قابل‌تشخیص پایان می‌یابد، نه با خروجی خالیِ موفق.
- Chat Completions و taskهای ASR/Text از یک ظرفیت مشترک استفاده می‌کنند. Chatهای پذیرفته‌شده به‌ترتیب ورود (FIFO) در حالت `queued` می‌مانند؛ پس از پر شدن سقف صف، درخواست جدید با `503` رد می‌شود.
- `ASR_QUEUE_LIMIT`، `ASR_QUEUE_MAX_AUDIO_MB` و `ASR_QUEUE_MAX_MODEL_RUNS`: سقف تعداد task، مجموع فایل صوتی فعال و تعداد model-runهای فعال.
- `ASR_HTTP_MAX_IN_FLIGHT`، `ASR_SYNC_CHAT_MAX_IN_FLIGHT` و `ASR_HTTP_ADMISSION_WAIT_SECONDS`: سقف کل درخواست‌های HTTP، سقف اتصال‌های همگام Chat و مهلت کوتاه ورود قبل از پاسخ کنترل‌شدهٔ `503`. اندازهٔ multipart و بدنه‌های JSON نیز جداگانه با `ASR_HTTP_MAX_BODY_MB` و `ASR_HTTP_MAX_JSON_BODY_MB` محدود می‌شود.
- `ASR_MAX_CONCURRENT_UPLOADS`: سقف uploadهای عبوری هم‌زمان از API. برای فایل بزرگ، upload مستقیم MinIO ترجیح دارد.
- `ASR_SPOOL_MAX_MB`، `ASR_SPOOL_MIN_FREE_MB` و `ASR_SPOOL_MIN_FREE_PERCENT`: بودجه و حداقل فضای آزاد spool؛ قبل و حین upload کنترل می‌شوند.
- `ASR_SYNC_CHAT_WAIT_SECONDS`: بیشترین زمان بازماندن اتصال `/v1/chat/completions` (پیش‌فرض ۱۲۰ ثانیه). task پس از timeout در صف می‌ماند و از `Location` قابل پیگیری است.
- `ASR_TASK_MAX_ATTEMPTS`: تعداد کل تلاش‌ها (پیش‌فرض ۲).
- `ASR_CHAT_TASK_TIMEOUT_SECONDS`: سقف اجرای هر تلاش تحلیل چت ناهمگام، شامل بارگذاری مدل (پیش‌فرض ۹۰۰ ثانیه، حداقل ۱۲۱). پس از اتمام زمان، فرایند inference همان تلاش متوقف می‌شود؛ پس از آخرین تلاش وضعیت `failed` با `error_code: "task_timeout"` است. این تنظیم بر Chat Completions قدیمی، ASR و Text اثری ندارد.
- `ASR_MAX_MODELS_PER_TASK`: حداکثر تعداد مدل مرتب در هر درخواست (پیش‌فرض ۵).
- `ASR_TASK_STALE_SECONDS`: مهلت lease برای بازیابی پس از crash.
- `ASR_TASK_RESULT_TTL_HOURS`: عمر نتیجه و metadata تسک (پیش‌فرض ۷ روز).

### تحلیل متنی سفارشی بدون اتصال HTTP طولانی

این API علاوه بر `/v1/chat/completions` ارائه می‌شود و مسیر پیشنهادی برای کار طولانی است. درخواست زیر فقط پس از ثبت در SQLite روی volume پایدار `/data` پاسخ می‌دهد، نه پس از بارگذاری/اجرای مدل. مدل باید از پیش نصب شده باشد و کلید دسترسی `chat` (یا `inference`) به آن داشته باشد. متن system آزاد است؛ خروجی JSON مورد نظر باید در همین متن درخواست شود و محتوای `message.content` نتیجه به همان شکل متن مدل تحویل می‌شود (JSON درونی خودکار parse یا تضمین نمی‌شود).

```http
POST /v1/chat/tasks
Authorization: Bearer YOUR_KEY
Idempotency-Key: call-analysis-123
Content-Type: application/json

{"model":"dorna-8b-q4_k_m","messages":[{"role":"system","content":"تماس را تحلیل کن؛ فقط JSON با کلیدهای summary و sentiment برگردان."},{"role":"user","content":"متن مکالمه فارسی..."}],"temperature":0.2,"max_tokens":1024}
```

پاسخ `202` شامل `Location: /v1/tasks/TASK_ID` و `Retry-After: 2` است؛ نمونهٔ فیلدهای اصلی:

```json
{"task_id":"a1b2c3","kind":"chat_async","status":"queued","status_url":"/v1/tasks/a1b2c3","result_url":"/v1/tasks/a1b2c3/result","attempts":0,"max_attempts":2,"error_code":null}
```

با همان کلید API، `GET /v1/tasks/TASK_ID` وضعیت‌های `queued`، `running`، `succeeded`، `failed` و `cancelled` را برمی‌گرداند (زمان backoff تلاش مجدد به‌صورت `queued` نمایش داده می‌شود). `GET /v1/tasks/TASK_ID/result` قبل از موفقیت `409` با `{"error":{"code":"result_not_ready","message":"Task is queued"}}` و بعد از موفقیت خود پاسخ کامل `chat.completion` مانند `{"id":"chatcmpl-...","object":"chat.completion","model":"dorna-8b-q4_k_m","choices":[{"index":0,"message":{"role":"assistant","content":"{\"summary\":\"...\"}"},"finish_reason":"stop"}]}` را برمی‌گرداند. وضعیت شکست `error_code` برابر `task_timeout` یا `model_failure` دارد؛ در دریافت نتیجه نیز `409` با همین کد بازگردانده می‌شود. `DELETE /v1/tasks/TASK_ID` کار صف‌شده را لغو می‌کند یا لغو کار جاری را درخواست می‌کند؛ فرایند کار جاری حداکثر طی چند ثانیه متوقف می‌شود. نتیجهٔ لغو قابل دریافت نیست (`409 task_cancelled`).

ثبت درخواست با کلید تکراری و بدنهٔ برابر همان `task_id` را حتی پس از restart می‌دهد؛ تغییر محتوا `409 idempotency_conflict` است. کلید برای هر API key جداست؛ پس از حذف دادهٔ منقضی‌شده، می‌توان همان کلید را برای کار تازه استفاده کرد. کدهای دیگر: `400 invalid_request`/`invalid_idempotency_key`، `401 authentication_failed`، `403 access_denied`، `404 model_unavailable` (یا برای task متعلق به کلید دیگر `task_not_found`)، `503 queue_full` همراه `Retry-After: 10`. خطاها قالب `{"error":{"code":"...","message":"..."}}` دارند. prompts و کلیدهای API در log ثبت نمی‌شوند؛ فقط صاحب همان کلید به محتوای task و نتیجه دسترسی دارد.

تعداد تلاش‌ها `ASR_TASK_MAX_ATTEMPTS` (پیش‌فرض ۲) است. کار صف‌شده پس از restart از SQLite بازیابی می‌شود؛ کار نیمه‌تمام، پس از توقف فرایند inference قبلی، با همان task ID در صورت باقی‌بودن تلاش‌ها دوباره اجرا می‌شود و در غیر این صورت شکست می‌خورد. این سیاست at-least-once برای تلاش قطع‌شده است، نه تضمین اجرای دقیقاً یک‌بارهٔ native inference؛ کار موفق دوباره اجرا نمی‌شود. نتیجه و idempotency تا `ASR_TASK_RESULT_TTL_HOURS` ساعت پس از پایان باقی می‌مانند و پاک‌سازی هنگام راه‌اندازی و سپس تقریباً هر ساعت انجام می‌شود. فقط یک instance سرویس روی volume SQLite پشتیبانی می‌شود.

این backend برای یک instance طراحی شده و بدون Redis/RabbitMQ نیز پایدار است. برای اجرای
چند سرور روی چند میزبان، queue باید با broker مشترک مانند Redis/RabbitMQ و worker مستقل
جایگزین شود؛ SQLite روی filesystem شبکه‌ای انتخاب مناسبی برای آن سناریو نیست.

## Upload مستقیم و قابل‌ادامه با MinIO

مسیر قدیمی `POST /v1/audio/transcriptions` برای سازگاری باقی می‌ماند، اما فایل را از
طریق HTTP سرویس ASR دریافت می‌کند. برای ترافیک بالا، profile اختیاری `object-storage`
یک MinIO خصوصی اجرا می‌کند و کلاینت partهای فایل را مستقیماً با URL امضاشده upload می‌کند.
در نتیجه ASR فقط metadata دریافت می‌کند و worker فایل را تنها وقتی ظرفیت inference آزاد
شد دانلود می‌کند.

پیش از اجرا، در `.env` مقادیر یکتا و امن زیر را قرار دهید:

```env
MINIO_ROOT_USER=asr-storage-admin
MINIO_ROOT_PASSWORD=a-long-random-secret-at-least-20-characters
ASR_S3_ENDPOINT=http://minio:9000
ASR_S3_PUBLIC_ENDPOINT=https://uploads.example.com
ASR_S3_BUCKET=asr-uploads
MINIO_API_CORS_ALLOW_ORIGIN=https://aiservice.voicesanj.ir
```

`ASR_S3_PUBLIC_ENDPOINT` باید یک hostname مستقل HTTPS باشد که Nginx Proxy Manager آن را
به پورت API MinIO (`9000`) forward می‌کند. از path زیر دامنهٔ اصلی استفاده نکنید؛ امضای
S3 به hostname و path حساس است. در NPM یک Proxy Host با `uploads.example.com` بسازید و
آن را فقط به MinIO:9000 متصل کنید؛ console پورت `9001` را عمومی نکنید. اگر NPM و این
compose روی یک Docker host هستند، هر دو را به یک network مشترک وصل کنید و در NPM upstream
را `minio:9000` قرار دهید. اگر روی دو میزبان هستند، فقط IP خصوصی MinIO:9000 را در firewall
برای IP سرور NPM مجاز کنید.

سپس اجرا کنید:

```bash
docker compose --profile object-storage up -d --build
```

فایل [`docker/minio/cors.json`](docker/minio/cors.json) origin پنل فعلی را مجاز می‌کند؛
اگر کلاینت وب شما روی دامنهٔ دیگری است، آن origin را پیش از deploy تغییر دهید. bucket خصوصی
است و URLهای part تنها ۱۵ دقیقه اعتبار دارند. MinIO روی همان VPS، پردازش ASR را از ترافیک
upload جدا می‌کند اما ظرفیت اینترنت آن VPS را افزایش نمی‌دهد؛ برای رفع اشباع لینک، همین API
را با endpoint عمومی R2/S3 یا MinIO روی یک سرور upload جدا استفاده کنید.

گردش کار کلاینت جدید:

1. `POST /v1/uploads` با `filename`، `audio_bytes`، `content_type` و در صورت امکان `sha256`.
2. برای هر part، `POST /v1/uploads/{upload_id}/parts/{part_number}` و سپس `PUT` مستقیم bytes
   به `url` پاسخ. مقدار header `ETag` هر پاسخ PUT را نگه دارید.
3. `POST /v1/uploads/{upload_id}/complete` با `parts: [{part_number, etag}]` به‌ترتیب صعودی.
4. `POST /v1/uploads/{upload_id}/transcriptions` با تنظیمات مدل. پاسخ همان `202` و `task_id`
   قرارداد قبلی را دارد.

برای ارسال اختیاری فایل gzip، در upload معمولی فیلد multipart `audio_encoding=gzip` را
ارسال کنید. در upload مستقیم، همراه `audio_encoding: "gzip"` مقدار دقیق
`uncompressed_audio_bytes` نیز الزامی است؛ `audio_bytes` همچنان حجم فایل فشرده و مبنای
partها است. سرویس gzip را پیش از پذیرش بررسی می‌کند و سقف ASR بر اساس حجم بازشده اعمال
می‌شود.

نمونهٔ ایجاد upload مستقیم gzip:

```json
{
  "filename": "sample.mp3",
  "audio_bytes": 124000,
  "audio_encoding": "gzip",
  "uncompressed_audio_bytes": 480000
}
```

part پیش‌فرض ۱۶MB است؛ برای فایل ۵۰۰MB، ۳۲ PUT قابل retry خواهید داشت. `sha256` اختیاری در
هنگام اجرای worker روی فایل دانلودشده اعتبارسنجی می‌شود تا کلاینت نتواند محتوای دیگری را با
metadata معتبر وارد صف کند.

## API رونویسی

```bash
curl -i http://localhost:8000/v1/audio/transcriptions \
  -H 'Authorization: Bearer YOUR_KEY' \
  -H 'Idempotency-Key: upload-42' \
  -F file=@sample.mp3 \
  -F model=shenava-koochik \
  -F response_format=verbose_json
```

نمونهٔ gzip:

```bash
curl -i http://localhost:8000/v1/audio/transcriptions \
  -H 'Authorization: Bearer YOUR_KEY' \
  -F file=@sample.mp3.gz \
  -F audio_encoding=gzip \
  -F model=shenava-koochik
```

برای اجرای چند مدل روی همان فایل، فیلد multipart به نام `models` را به ترتیب دلخواه
تکرار کنید. مدل‌ها به‌صورت ترتیبی اجرا می‌شوند و شکست یک مدل مانع اجرای مدل بعدی نیست:

```bash
curl -i http://localhost:8000/v1/audio/transcriptions \
  -H 'Authorization: Bearer YOUR_KEY' \
  -H 'Idempotency-Key: multi-upload-42' \
  -F file=@sample.mp3 \
  -F models=shenava-koochik \
  -F models=whisper-persian-v4 \
  -F models=buzzasr-persian \
  -F response_format=verbose_json
```

درخواست باید دقیقاً یکی از `model` یا `models` را داشته باشد. شناسه‌های تکراری مجاز
نیستند و ترتیب آرایه/فیلدها، ترتیب قطعی اجرا است. پاسخ نتیجه برای درخواست چندمدلی همیشه
یک JSON شامل `results` مرتب، وضعیت، زمان، خطا و خروجی مستقل هر مدل است. وضعیت کلی
`partially_succeeded` یعنی حداقل یک مدل موفق و حداقل یک مدل ناموفق یا لغوشده بوده است.
نتیجه در وضعیت‌های `succeeded` و `partially_succeeded` و برای batch چندمدلی کاملاً
ناموفق نیز قابل دریافت است تا خطای مستقل همه مدل‌ها از دست نرود. برای درخواست
تک‌مدلی، قرارداد و media typeهای قبلی بدون تغییر حفظ شده‌اند.

پاسخ شامل `task_id` و `status_url` است. کلاینت وضعیت را poll و پس از موفقیت نتیجه را دریافت می‌کند:

```bash
curl -H 'Authorization: Bearer YOUR_KEY' http://localhost:8000/v1/tasks/TASK_ID
curl -H 'Authorization: Bearer YOUR_KEY' http://localhost:8000/v1/tasks/TASK_ID/result
```

ارسال دوباره همان `Idempotency-Key` همان تسک را برمی‌گرداند و کار تکراری ایجاد نمی‌کند.
اگر همان کلید با ترتیب مدل‌ها، تنظیمات یا محتوای متفاوت استفاده شود، سرویس `409 Conflict`
برمی‌گرداند.
ارسال دقیقاً یکی از فیلدهای `model` یا `models` اجباری است؛ مفهوم مدل منتخب یا فعال وجود ندارد و همه مدل‌های نصب‌شده آماده
استفاده هستند. فرمت‌های `json`،
`verbose_json`، `text`، `srt` و `vtt` در endpoint نتیجه حفظ شده‌اند. مستندات تعاملی
Swagger در `/docs` قرار دارد. مستندات ReDoc کاربران در `/redoc/user` (با alias قدیمی
`/redoc`) و مستندات ReDoc مدیران در `/redoc/admin` در دسترس است. schemaهای تفکیک‌شده
نیز به‌ترتیب از `/openapi/user.json` و `/openapi/admin.json` قابل دریافت‌اند و
`/openapi.json` قرارداد کامل سرویس را برمی‌گرداند. لینک هر دو ReDoc در پنل مدیریت نیز
نمایش داده می‌شود.

## ساختار API

- `app.py`: entrypoint کوچک و ثابت ASGI
- `asr_service/api/`: endpointها، مدل‌های request/response و اسناد OpenAPI/ReDoc
- `asr_service/domain/`: کاتالوگ و تعریف مدل‌های دامنه
- `asr_service/services/`: صف، inference، پردازش متن، دانلود و آماده‌سازی مدل‌ها
- `asr_service/infrastructure/`: دیتابیس و تنظیمات شبکه
- `asr_service/web/`: رابط پنل مدیریت

## API مدیریت

- `GET /api/models`
- `POST /api/models/{id}/install|pause|resume`
- `GET /api/models/{id}/status`
- `GET /api/stats`
- `GET /api/usage?page=1&page_size=20` و `GET /api/usage/{id}` برای جزئیات و لاگ مدل‌ها
- `GET /v1/tasks/{task_id}` و `GET /v1/tasks/{task_id}/result`
- `DELETE /v1/tasks/{task_id}` برای لغو (اجرای جاری در نزدیک‌ترین نقطه امن متوقف می‌شود)
- `GET|PUT /api/proxy` و `POST /api/proxy/test`
- `POST /api/inference/interrupt-all` فقط برای مدیر: همهٔ taskهای فعال را لغو و process سرویس را restart می‌کند تا اجرای native فوراً متوقف شود.

کلید اصلی `ASR_API_KEY` تنها کلیدی است که به endpointهای مدیریتی `/api/*` دسترسی دارد.
کلیدهای کاربری از پنل ساخته می‌شوند، فقط یک‌بار نمایش داده می‌شوند و در دیتابیس صرفاً
به‌صورت SHA-256 (بهتر است همراه `ASR_API_KEY_PEPPER`) نگهداری می‌شوند. برای هر کلید می‌توان
مدل‌های مجاز، scope، سقف درخواست در دقیقه، انقضا و وضعیت فعال/مسدود را تعیین کرد. کلیدهای
کاربری به پنل یا API مدیریت دسترسی ندارند و هر کلید فقط taskهای خودش را می‌بیند.
`/health` عمومی است.

اگر GTCRN نصب باشد، پیش از هر موتور ASR به‌صورت خودکار اجرا می‌شود. برای Shenava وجود
Silero VAD کنترل می‌شود؛ segmentation اختصاصی Silero در این نسخه هنوز به worker پردازش
قطعه‌ای متصل نشده و Shenava فایل کامل را با resampling داخلی sherpa-onnx پردازش می‌کند.

## اصلاح متن و صورت‌جلسه با Dorna

پس از نصب یکی از نسخه‌های Dorna:

```bash
curl http://localhost:8000/v1/text/process \
  -H 'Authorization: Bearer YOUR_KEY' \
  -H 'Content-Type: application/json' \
  -d '{"model":"dorna-8b-q4_k_m","operation":"correction","text":"متن خام رونویسی"}'
```

برای اجرای ترتیبی چند مدل Dorna از `models` استفاده کنید:

```json
{
  "models": ["dorna-8b-q4_k_m", "dorna-8b-q3_k_m"],
  "operation": "correction",
  "style": "formal",
  "text": "متن خام رونویسی"
}
```

در تاریخچه پنل، هر درخواست یک سطر خلاصه در خود جدول دارد. با بازکردن همان سطر، مدل‌ها
به ترتیب اجرا همراه با وضعیت، تعداد تلاش، زمان پردازش، خطا و لاگ مستقل نمایش داده می‌شوند.
اطلاعات جزئی فقط هنگام بازشدن آکاردئون دریافت می‌شود تا تاریخچه‌های بزرگ سبک بمانند.

برای صورت‌جلسه، `operation` را `minutes` و `style` را یکی از `formal`،
`semi_formal` یا `action` قرار دهید. دقیقاً یکی از `model` یا `models` اجباری است. اجرای پیش‌فرض CPU است و با
`DORNA_GPU_LAYERS` قابل تنظیم است.

## API سازگار با OpenAI برای مدل‌های متنی

هر مدل GGUF نصب‌شده با همان سه ورودی متداول قابل استفاده است: آدرس پایه، API key و نام
مدل. آدرس پایه برای SDKهای OpenAI برابر `http://localhost:8000/v1` است:

```bash
curl http://localhost:8000/v1/chat/completions \
  -H 'Authorization: Bearer YOUR_KEY' \
  -H 'Content-Type: application/json' \
  -d '{"model":"dorna-8b-q4_k_m","messages":[{"role":"user","content":"سلام"}]}'
```

پاسخ non-streaming از نوع `chat.completion` و پاسخ `stream:true` به‌صورت SSE و
`chat.completion.chunk` با پیام پایانی `[DONE]` است. `GET /v1/models` به‌صورت پیش‌فرض فقط مدل‌های متنی
را برمی‌گرداند. برای مدل‌های صوتی از `GET /v1/models?kind=asr` و برای هر دو از
`GET /v1/models?kind=all` استفاده کنید. خروجی فقط مدل‌های نصب‌شده و مجاز برای همان کلید
را با فیلد `kind` در قالب OpenAI برمی‌گرداند؛ مدل‌های صوتی
فقط در مسیر تبدیل صوت و مدل‌های متنی فقط در مسیر چت قابل استفاده‌اند. ثبت مدل در پنل به‌تنهایی
کافی نیست و نصب موفق (ایجاد `.complete`) نیز لازم است. قابلیت فعلی برای پیام متنی
و پارامترهای `temperature`، `top_p`، `max_tokens`/`max_completion_tokens`، `stop`،
`seed` و penaltyها پیاده شده است؛ ورودی multimodal و tool calling برای مدل‌های GGUF
فعلی تضمین نشده است.

## مدل‌های تصمیم‌گیری CPU

مدل‌های تصمیم‌گیری از مسیر `POST /v1/decisions` اجرا می‌شوند و از endpointهای chat یا
text-processing استفاده نمی‌کنند. فقط modelهای نصب‌شده با `kind=decision` پذیرفته می‌شوند.
کلید API باید scope `decision` یا `inference` و دسترسی به همان model را داشته باشد. هر پاسخ
شامل confidence، margin و `abstained` است و در confidence پایین هیچ fallback مولدی اجرا نمی‌شود.

در پنل مدل‌ها، Decision را انتخاب کنید. برای Hugging Face، repository عمومی و commit دقیق
۴۰ کاراکتری وارد کنید؛ سرور manifest و SHA-256 فایل‌ها را پیش از ثبت resolve می‌کند. برای
manifest مستقیم، هر خط به شکل `filename | https://... | sha256` است. دانلود پس از checksum و
offline smoke به‌صورت atomic نصب می‌شود. URL دارای credential و HTTP پذیرفته نمی‌شود.

نمونهٔ درخواست:

```bash
curl http://localhost:8000/v1/decisions \
  -H 'Authorization: Bearer YOUR_KEY' \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: decision-001' \
  -d '{"model":"support-router","state":"مشتری درخواست بازپرداخت دارد","questions":{"intent":{"type":"choice","instructions":"Choose one intent","criteria":["refund","billing","other"]}}}'
```

اگر نتیجه در زمان `ASR_DECISION_SYNC_WAIT_SECONDS` آماده باشد پاسخ `200` می‌گیرد؛ در غیر این
صورت `202` با `task_id` و header `Location` برای polling بازمی‌گردد. تنظیمات پایهٔ production
برای تصمیم‌گیری `ASR_DECISION_MAX_CONCURRENT=2`، `ASR_DECISION_CPU_THREADS=7`،
`ASR_DECISION_QUEUE_LIMIT=256`، `ASR_DECISION_TIMEOUT_SECONDS=20` و
`ASR_DECISION_CONFIDENCE_THRESHOLD=0.72` هستند.

## مدل سفارشی، API key و CORS

## 9Router

از بخش «تنظیمات» پنل ادمین می‌توان 9Router را برای ASR و Text/Chat به‌صورت مستقل فعال کرد. ابتدا `ASR_9ROUTER_SECRETS_KEY` را با یک Fernet key پایدار در محیط سرویس قرار دهید؛ کلید API 9Router پس از ثبت در SQLite رمزگذاری می‌شود و فقط وضعیت ثبت‌شدن آن در پنل نمایش داده می‌شود. آدرس پیش‌فرض `http://127.0.0.1:20128` است و می‌تواند به استقرار خصوصی یا Cloud تغییر کند.

دکمه «آزمایش اتصال» مسیرهای `/api/health` و `/v1/models` را بررسی می‌کند؛ «بازیابی مدل‌ها» فهرست Chat و STT را جداگانه می‌خواند. 9Router باید با API key و نسخهٔ امن پشت reverse proxy اجرا شود. هنگام فعال‌بودن، مدل انتخاب‌شده برای همان قابلیت تنها مدل قابل‌استفاده از API سرویس است و خطاهای شبکه، timeout، `429` و `5xx` طبق retry پایدار task تکرار می‌شوند.

در پنل مدیریت، مدل متنی GGUF با شناسه، نام نمایشی، URL مستقیم دانلود، نام فایل، اندازه
اختیاری و SHA-256 اختیاری ثبت می‌شود و سپس با همان دکمه نصب مدل‌های داخلی دانلود خواهد شد.
ثبت متناظر APIها با `POST /api/models` نیز ممکن است.

بخش «امنیت و شبکه» پنل، ساخت و مسدودسازی کلیدها و allowlist مربوط به CORS و IP را مدیریت
می‌کند. Origin باید کامل باشد (برای نمونه `https://app.example.com`). IP می‌تواند یک آدرس
یا CIDR باشد. Originهای خالی یعنی پاسخ CORS صادر نشود؛ IPهای خالی یعنی محدودیت IP روی
`/v1/*` اعمال نشود. سیاست جدید بدون restart اعمال می‌شود. توجه کنید CORS فقط مرورگر را
کنترل می‌کند، در حالی‌که IP allowlist در سمت سرور enforce می‌شود.
