# پیکربندی Whisper روی CPU

## نتیجه

برای سرور CPU محور این سرویس، پیکربندی پیش‌فرض عملیاتی `int8`، یک اجرای هم‌زمان، threadهای خودکار متناسب با cgroup، `beam_size=2` و `temperature=0` است. این انتخاب کیفیت مدل فارسی را تغییر نمی‌دهد، اما هزینهٔ جست‌وجوی decoding و تکرارهای temperature fallback را محدود می‌کند. خروجی segment و timestamp نیز حفظ می‌شود؛ بنابراین SRT و VTT همچنان قابل تولید هستند.

## شواهد

| موضوع | شواهد | تصمیم در سرویس |
| --- | --- | --- |
| مدل انتخاب‌شده | مدل `nezamisafa/whisper-persian-v4` یک checkpoint فارسی Whisper با حجم 6.18GB است. | برای کیفیت فارسی نگه داشته شد؛ تعویض مدل بدون ارزیابی دادهٔ فارسی انجام نشد. |
| quantization CPU | CTranslate2 استفاده از `int8` را برای CPU توصیه می‌کند. | `ASR_COMPUTE_TYPE=int8` باقی ماند. |
| beam search | faster-whisper به‌طور پیش‌فرض beam=5 دارد، در حالی که OpenAI Whisper beam=1 را به‌کار می‌برد. CTranslate2 نیز beam=1 را گزینهٔ سریع‌تر معرفی می‌کند. | پیش‌فرض API از 5 به 2 تغییر کرد؛ client همچنان می‌تواند 1 تا 10 انتخاب کند. |
| fallback دما | faster-whisper به‌طور پیش‌فرض دماهای 0 تا 1 را برای fallback امتحان می‌کند. maintainer پروژه صراحتاً آن را علت کندی شدید فایل‌های دشوار دانسته است. | `temperature=0` پیش‌فرض شد؛ یک decode قطعی اجرا می‌شود. |
| threadها | CTranslate2 از OpenMP برای intra-op parallelism استفاده می‌کند و توصیه می‌کند حاصل inter/intra threads از هسته‌های فیزیکی بیشتر نشود. | محدودیت صریح `OMP_NUM_THREADS=1` از image حذف شد؛ برنامه `cpu_threads` را بر اساس affinity/cgroup محاسبه می‌کند. |
| VAD | faster-whisper استفاده از VAD را برای حذف سکوت پشتیبانی می‌کند. | `vad_filter=True` پیش‌فرض باقی ماند. |

## دلیل کندی مشاهده‌شده

در رخداد بررسی‌شده، model loading حدود 5 ثانیه و denoising حدود 44 ثانیه بود؛ زمان باقی‌مانده در `Decoding audio with faster-whisper` مصرف شد. با beam=5، temperature fallback پیش‌فرض و محدودیت OpenMP به یک thread، این رفتار با یک مدل Whisper فارسی حدود 2 میلیارد پارامتر سازگار است. هیچ شواهدی از کمبود RAM، swap یا گلوگاه دیسک وجود نداشت.

## تنظیمات عملیاتی

```dotenv
ASR_DEVICE=cpu
ASR_COMPUTE_TYPE=int8
ASR_MAX_CONCURRENT=1
ASR_TASK_WORKERS=1
ASR_CPU_THREADS=0
ASR_WHISPER_BEAM_SIZE=2
ASR_WHISPER_TEMPERATURE=0
```

`ASR_CPU_THREADS=0` یعنی برنامه از CPU affinity و cgroup quota استفاده کند. برای throughput بیشینه و فایل‌های کم‌ریسک، beam را `1` کنید. برای ارزیابی دقت، beam=2 و beam=5 را روی مجموعه‌ای ثابت از فایل‌های فارسی و با WER/CER مقایسه کنید؛ بدون چنین benchmarkی، ادعای برتری دقت برای beam=5 قابل اتکا نیست.

## اثر تغییرات و محدودیت‌ها

این تغییرها برای درخواست‌های جدیدی اعمال می‌شوند که client مقدار `beam_size` را صریحاً ارسال نکند. clientهایی که `beam_size=5` می‌فرستند همچنان همان مقدار را دریافت می‌کنند؛ این رفتار عمدی است تا قرارداد API و امکان انتخاب کیفیت حفظ شود. `ASR_WHISPER_TEMPERATURE=0` برای همهٔ درخواست‌های Whisper اعمال می‌شود، مگر این‌که مقدار environment را پیش از startup تغییر دهید.

حذف `OMP_NUM_THREADS=1` به‌تنهایی تعداد thread را نامحدود نمی‌کند. کد سرویس `ASR_CPU_THREADS=0` را با CPU affinity و cgroup quota ترکیب می‌کند و سپس مقدار محاسبه‌شده را به `WhisperModel(cpu_threads=...)` می‌دهد. با یک اجرای هم‌زمان، هدف استفاده از ظرفیت قابل مشاهدهٔ کانتینر است، بدون این‌که inferenceهای هم‌زمان باعث oversubscription شوند.

Beam=2 یک مصالحه است، نه تضمین بهترین WER برای هر فایل. beam=1 گزینهٔ throughput است و beam=5 گزینهٔ quality-first. temperature=0 نیز fallback بازیابی متن را حذف می‌کند؛ برای فایل‌های بسیار بد ممکن است کیفیت پایین‌تر از حالت fallback باشد، اما زمان اجرا قابل پیش‌بینی‌تر و احتمال loopهای طولانی کمتر می‌شود. این تصمیم برای سرویس production CPU-bound مناسب‌تر است، زیرا درخواست 8 دقیقه‌ای قبلی عملاً به RTF بالاتر از 5.4 رسید.

## سنجش پس از deploy

برای ارزیابی معتبر، سه فایل ثابت فارسی با گفتار تمیز، نویز متوسط و گفتار چندنفره انتخاب کنید. هر تنظیم را دست‌کم دو بار پس از گرم‌شدن model اجرا کنید و زمان wall-clock، `processing_seconds`، `duration_seconds`، میانگین CPU و متن خروجی را ثبت کنید.

| پروفایل | beam | دما | هدف |
| --- | ---: | ---: | --- |
| Production (پیش‌فرض) | 2 | 0 | تعادل سرعت، کیفیت و زمان قابل پیش‌بینی |
| Fast | 1 | 0 | بیشترین throughput برای متن‌های کم‌ریسک |
| Quality audit | 5 | 0 | مرجع بررسی کیفیت روی مجموعهٔ ثابت |
| Legacy comparison | 5 | fallback پیش‌فرض | فقط برای سنجش، نه پیش‌فرض production |

دو معیار اصلی `RTF = processing_seconds / duration_seconds` و نرخ خطای واژه/نویسه روی مرجع انسانی هستند. معیار RTF باید برای فایل‌های هم‌نوع گزارش شود؛ مقایسهٔ صرف زمان خام بین فایل‌های با گفتار و سکوت متفاوت معتبر نیست. اگر beam=2 دقت قابل قبول دارد، آن را حفظ کنید؛ اگر خطا فقط در یک دامنه مانند نام‌ها یا لهجه‌ها رخ داد، به‌جای بالا بردن global beam، برای همان client یا endpoint beam=5 ارسال کنید.

## دستور deploy و rollback

پس از انتقال این تغییرها به سرور، image باید rebuild شود؛ تغییر environment یا Dockerfile با restart ساده اعمال نمی‌شود:

```bash
docker compose up -d --build persian-asr
docker compose exec persian-asr sh -c 'env | grep -E "^(ASR_WHISPER|ASR_CPU_THREADS|ASR_MAX_CONCURRENT|OMP_NUM_THREADS)="'
```

نبودن `OMP_NUM_THREADS` در خروجی درست است. برای rollback سریع، در `.env` مقدار `ASR_WHISPER_BEAM_SIZE=5` بگذارید و سرویس را rebuild/recreate کنید. برای بازگرداندن fallback چنددمایی، نسخهٔ قبلی کد لازم است، زیرا تنظیم جدید عمداً یک دمای قطعی استفاده می‌کند.

## منابع

1. Hugging Face, [nezamisafa/whisper-persian-v4](https://huggingface.co/nezamisafa/whisper-persian-v4) — معماری، زبان، مجوز و اندازهٔ artifact.
2. SYSTRAN, [faster-whisper README](https://github.com/SYSTRAN/faster-whisper/blob/master/README.md) — benchmarkهای CPU، تفاوت beam پیش‌فرض 5 با OpenAI Whisper، VAD و راهنمای threadها.
3. SYSTRAN, [transcribe.py](https://github.com/SYSTRAN/faster-whisper/blob/master/faster_whisper/transcribe.py) — پیش‌فرض `beam_size=5` و فهرست temperature fallback.
4. SYSTRAN maintainer, [Discussion #169](https://github.com/SYSTRAN/faster-whisper/discussions/169) — توصیهٔ `cpu_threads` متناسب با هسته‌ها، beam=1 و temperature=0 برای کندی ناشی از fallback.
5. OpenNMT, [CTranslate2 multithreading](https://opennmt.net/CTranslate2/parallel.html) و [performance tips](https://opennmt.net/CTranslate2/performance.html) — intra/inter-op threading، int8 و جلوگیری از oversubscription.
