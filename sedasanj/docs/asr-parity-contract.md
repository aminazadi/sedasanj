# قرارداد برابری تبدیل صوت به متن (ASR Parity Contract) — نسخهٔ ۱

هدف: رونویسی لوکال «جلسه‌نگار» همان زنجیرهٔ سرور (aiservice + `worker_asr` صداسنج) را اجرا کند. این سند مشخص می‌کند «همان» یعنی چه، کجا امروز یکی نیست، و کدام تست هر بند را قفل می‌کند.

> برچسب‌ها: **[موجود]** در کد سرور تأیید شده (با مسیر فایل). **[پیشنهاد]** هنوز در هیچ‌کدام پیاده نشده و نیاز به تأیید نگهدارنده دارد. **⚠** نیاز به تأیید آزمایشگاهی.

## ۱. تعریف برابری

خروجی بایت‌به‌بایت یکسان ممکن نیست (سرور CPU/INT8 یا GPU/FP32 با VAD انرژی؛ موبایل با Silero). برابری یعنی:

1. همان وزن‌ها و tokens: `shenava-koochik-v1-5-rnnt` (INT8)، decode حریصانه با `model_type="nemo_transducer"`، ورودی float32 مونو ۱۶kHz، بدون hotword و LM. [موجود] `aiservice/asr_service/services/inference.py`
2. همان زنجیرهٔ پیش‌پردازش با همان ثابت‌ها (بخش ۳).
3. همان نرمال‌سازی و ادغام (بخش ۴ و ۵).
4. همان schema خروجی (بخش ۶).
5. معیار عددی: اختلاف WER اپ در برابر سرور-CPU-INT8 روی مجموعهٔ طلایی ≤ ۲٪ مطلق. [پیشنهاد؛ عدد نهایی پس از ثبت Baseline] ابزار: `sedasanj/scripts/asr_eval.py compare`.

## ۲. صوت ورودی

| مورد | مقدار | منبع |
|---|---|---|
| خروجی پیش‌پردازش | WAV، pcm_s16le، ۱۶kHz، مونو | `audio.py::preprocess_mono_audio` |
| ingest پذیرفته | ۸kHz یا ۱۶kHz، ۱ یا ۲ کانال | `audio.py::ALLOWED_SAMPLE_RATES` |
| استریو | تقسیم به دو فایل مونو، ASR مستقل هر کانال | `worker_asr/main.py::_transcribe_tracks` |
| برچسب کانال | `0=caller`، `1=agent` | `main.py::CHANNEL_LABELS` |

جلسه‌نگار فقط میکروفن مونو ۱۶kHz ضبط می‌کند؛ در schema مقدار `channel=0`.

## ۳. پیش‌پردازش

پیش‌فرض سرور: **خاموش** (`audio_preprocessing_enabled=False`)؛ در حالت خاموش فقط `aresample=16000`. [موجود]

فایل مرجع ماشین‌خوان: `tests/fixtures/asr_parity/constants.json`. خلاصه:

- denoise: `afftdn=nr=12:nf=-50:tn=1` (balanced) یا `afftdn=nr=20:nf=-45:tn=1` (strong).
- enhance:
  - balanced: `highpass=f=80, lowpass=f=7600, dynaudnorm=f=150:g=9:p=0.95`
  - strong: `highpass=f=100, lowpass=f=7200, acompressor=…, dynaudnorm=f=120:g=7:p=0.92`
  - adaptive (تلفنی): `highpass=f=100, lowpass=f=7600` ← اندازه‌گیری `loudnorm=I=-23:TP=-2:LRA=11` ← `volume={gain}dB` ← `alimiter=limit=0.9:level=0`
- گین: `min(target − measured, max_gain)` با هدف −20 LUFS، سقف ۳۰dB، کاهش حداکثر ۶dB، کانال زیر −55 LUFS ساکت (گین ۰)، گین زیر ۰٫۵dB نادیده، گرد به ۰٫۱dB. `compute_gain_db` [موجود].
- شناسهٔ پیش‌پردازش: `preprocess:none` یا `denoise:<m>+enhance:<m>[@<target>LUFS/<gain>dB]`، ذخیره‌شده در `asr_version`. [موجود]

**شکاف امروز:** اپ از این زنجیره استفاده نمی‌کند؛ `_normalizeQuietAudio` (حذف DC و گین تا ۸× به RMS 0.08) و GTCRN اختیاری دارد. هیچ‌کدام در سرور نیست. تصمیم: فاز ۳ (پورت Dart + اعتبارسنجی عددی در برابر ffmpeg). `dynaudnorm` و `afftdn` معادل دقیق ندارند ⚠.

## ۴. نرمال‌سازی متن

سرور: `normalize(t) = " ".join(t.replace("ي","ی").replace("ك","ک").split())` [موجود]. بردارها: `normalization.json`.

| ورودی | سرور | اپ امروز |
|---|---|---|
| `ي`، `ك` عربی | → `ی`، `ک` | همین |
| فاصلهٔ زیاد/کناری | یک فاصله و trim | همین |
| ZWNJ | حفظ | حفظ |
| خط جدید، خط خالی | به فاصله | حفظ (حداکثر یک خط خالی) |
| `ى` (الف مقصوره) | حفظ | → `ی` |
| کشیده (ـ)، اعراب | حفظ | حذف |
| `ۀ` | حفظ | → `ه` (**باگ پنهان**) |

**باگ پنهان اپ:** `ۀ` به `ه`+U+0654 تبدیل می‌شود و بلافاصله U+0654 جزو بازهٔ اعراب `ً-ٟ` حذف می‌شود؛ نتیجهٔ مؤثر `ه` ساده است، نه آنچه کامنت می‌گوید. تست `jalase-negar/test/asr_parity_test.dart` رفتار فعلی را ثبت می‌کند.

**تصمیم لازم [پیشنهاد]:** یک رفتار واحد برای هر دو سمت. پیشنهاد: سطح پایهٔ سرور بماند، `ى→ی` و حذف کشیده/اعراب به سرور هم اضافه شود، `ۀ` دست‌نخورده بماند (باگ اپ اصلاح شود)، و خط جدید در متن نهایی حفظ شود نه تبدیل به فاصله (چون برای صورت‌جلسه مفید است). تغییر رفتاری سرور ⇒ تست + کد خطا + مقالهٔ راهنما + changelog؛ تا تأیید، هیچ‌کدام تغییر نکرده است.

## ۵. ادغام segmentها

`consolidate_segments(rows, merge_gap_ms=1200)` [موجود، `worker_asr/main.py`]: مرتب‌سازی `(start, channel, end)`، حذف متن خالی و کلیپ زمان منفی به ۰، ادغام segmentهای هم‌کانال متوالی با فاصلهٔ ≤ 1200ms (برابر مجاز است)، در هم‌پوشانی: متن برابر/پسوند ⇒ قبلی، پیشوند ⇒ بلندتر؛ confidence = کمینهٔ مقادیر غیر None؛ گفتار کانال دیگر حذف نمی‌شود. بردارها: `consolidation.json` (۱۱ مورد).

نکتهٔ رفتاری: در ادغام، `timestamp_source` پیش‌فرض `native` می‌شود؛ segment ادغام‌نشده بدون منبع، منبع ندارد.

**شکاف امروز:** اپ `_isDuplicateTranscript` دارد (برابری، شمول ≥۸ نویسه یا ۸۵٪ اشتراک token در ±1200ms) و ادغام نوبت ندارد. منطق متفاوت است. تصمیم: فاز ۴ پورت `consolidate_segments` به Dart با همین بردارها.

## ۶. Schema مشترک segment [پیشنهاد]

فایل: `segment.schema.json`. فیلدها: `id, channel (0|1), start_ms, end_ms, text, confidence?, speaker?, timestamp_source (native|vad_window|diarization|silero_vad), source (device|server)`.

- اپ امروز فقط `channel, startMs, endMs, text` دارد.
- سرور: `AsrSegment` (`t_start_ms, t_end_ms, text, confidence, metadata`) و `Utterance` در DB؛ `timestamp_source`/`speaker` در `metadata`.
- confidence روی RNNT سرور تهی است (فقط Whisper `exp(avg_logprob)` دارد). ⚠ بررسی کنید sherpa_onnx دارت برای transducer احتمال token می‌دهد یا نه.
- هیچ‌کدام word-level timestamp ندارند.

### شناسهٔ ASR [پیشنهاد]
سرور: `{engine.model_version}|{preprocess identity}`. برای دستگاه همان قالب + بخش بخش‌بندی: `shenava-koochik-v1-5-rnnt|preprocess:none|segmenter:silero-vad`.

## ۶.۱ وضعیت پیاده‌سازی اپ (فاز ۴)

- مدل پیشنهادی و اولِ فهرست: `shenava-koochik-v1-5-rnnt` (INT8)؛ CTC جایگزین است.
- `consolidateSegments` (Dart) با `consolidation.json` و `energyVadRegions` (Dart) با `energy_vad.json` تست می‌شوند؛ سمت سرور `energy_vad.json` را `aiservice/tests/test_asr_parity_vad.py` قفل می‌کند.
- جلسه‌های رونویسی‌شده segment قرارداد (`confidence` تهی، `speaker`، `timestamp_source`، `source=device`) و `meetings.asr_identity` دارند (DB نسخهٔ ۶).
- حالت `AsrSegmenter.serverEnergy` فقط برای مقایسهٔ کلیپ کوتاه (تا ۳۰ دقیقه) با رونویسی سرور است و از UI در دسترس نیست.
- هنوز یکی نشده: پیش‌پردازش (فاز ۳)، نرمال‌سازی (در انتظار تصمیم بخش ۴)، پارامترهای Silero (min 0.3s و padding 0.2s در برابر مقادیر فعلی ۰٫۲ و ۰٫۹ و پیش/پس‌رول ۰٫۷۵s) تا ثبت Baseline.
- **پیش‌نویس زنده:** هنگام ضبط، اپ متن را با `segmenter:silero-vad-live` می‌سازد (VAD روی جریان میکروفون، گین برای هر جمله، پیش/پس‌رول مثل مسیر معمول؛ بدون denoiser، بدون pass پوشش و بدون ادغام تا پایان ضبط). این متن **مرجع parity نیست**؛ با «رونویسی کامل» جایگزین می‌شود و `asr_identity` بازنویسی می‌شود. fixtureها و نسخهٔ قرارداد تغییر نمی‌کنند.
- sherpa_onnx ۱.۱۳.۶ برای transducer فقط `text`، `tokens` و `timestamps` (زمان token) می‌دهد؛ احتمال/confidence ندارد، پس `confidence` مثل سرور تهی می‌ماند.

## ۷. مغایرت‌های سرور که نباید به اپ منتقل شوند

- Silero VAD برای Shenava فقط gate نصب است، اجرا نمی‌شود (README ادعای دیگری دارد).
- پیش‌فرض `ensure_timestamps` بین `api/routers/tasks.py` (True) و `task_queue.py` (False) ناهمخوان است؛ آپلود مستقیم timestamp recovery نمی‌گیرد.
- `duration_after_vad` در schema غیرتهی ولی گاهی None.
- GTCRN فقط آخرین fallback Whisper است، نه پیش‌پردازش Shenava.

## ۸. اجرای تست‌ها

```bash
cd sedasanj && python -m pytest tests/test_asr_parity_contract.py tests/test_asr_eval.py
cd aiservice && python -m unittest tests.test_asr_parity_normalization
cd jalase-negar && flutter test test/asr_parity_test.dart
```

تست سرور اگر ثابتی، زنجیرهٔ فیلتر یا قاعدهٔ ادغام را بدون به‌روزرسانی fixture تغییر دهد می‌شکند. تست Dart مغایرت‌های ثبت‌شده (`app_today`) را قفل می‌کند؛ هنگام بستن هر شکاف، fixture و تست را با هم به‌روز کنید.

## ۹. تغییر قرارداد

fixtureها را همراه تغییر کد سرور و پورت اپ در یک تغییر به‌روز کنید و نسخهٔ سند را بالا ببرید. `consolidation.json` با اسکریپت از پیاده‌سازی سرور تولید و دستی بازبینی شده است؛ مقدار جدید را بدون بازبینی از خروجی کد کپی نکنید.
