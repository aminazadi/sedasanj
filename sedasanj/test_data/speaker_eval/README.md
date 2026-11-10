# مجموعهٔ ارزیابی گوینده (Speaker evaluation set)

این پوشه فقط راهنما را نگه می‌دارد. **صوت جلسه‌ها، صوت ثبت‌نام، برچسب‌ها و خروجی سیستم‌ها هرگز commit نمی‌شوند** (در `sedasanj/.gitignore` هستند): صدای آدم‌ها دادهٔ شخصی است. پیش از ضبط، از همهٔ گوینده‌ها رضایت بگیرید.

## چه چیزی لازم است

1. **۳ تا ۵ جلسهٔ واقعی فارسی**، هر کدام ۲ تا ۵ گوینده و ۵ تا ۱۵ دقیقه (جمعاً حدود ۳۰ دقیقه)، **با خود اپ روی گوشی** ضبط شده تا شرایط میکروفن مثل استفادهٔ واقعی باشد. دست‌کم یک جلسه با هم‌پوشانی صحبت و یک جلسه در محیط پرنویز.
2. **یک کلیپ ۱۵ تا ۲۰ ثانیه‌ای ثبت‌نام برای هر گوینده**، ضبط‌شده در صفحهٔ ثبت‌نام خود اپ.
3. **برچسب زمان‌دار گوینده** برای هر جلسه (چه کسی از چه ثانیه‌ای تا چه ثانیه‌ای حرف می‌زند). ساده‌ترین راه: پیش‌نویس بسازید و فقط اصلاح کنید (پایین).
4. دست‌کم یک گوینده در هر جلسه‌ی ارزیابی که **ثبت‌نام نشده** باشد (مهمان)، تا ببینیم اپ به غریبه‌ها اسم نمی‌دهد.

## ساختار محلی

```
test_data/speaker_eval/
  manifest.json            # از manifest.example.json بسازید
  audio/<id>.wav           # PCM16، mono، 16kHz
  enroll/<name>.wav        # PCM16، mono، 16kHz
  truth/<id>.json          # [{"start": 0.0, "end": 3.2, "speaker": "Ali"}, ...]
  hypotheses/<system>.json # خروجی bench_speaker_test.dart
```

- زمان‌ها ثانیه‌اند. بخش‌های دو گوینده می‌توانند هم‌پوشانی داشته باشند.
- مکث‌ها و سکوت‌ها را **برچسب نزنید**؛ فقط جایی که کسی واقعاً حرف می‌زند. وگرنه هر مکث «گفتار از دست رفته» حساب می‌شود.
- نام کسی که در `enrolled` نیست یعنی «غریبه»؛ اپ باید او را `ناشناس N` بنامد.
- صوت غیر 16kHz mono را ابتدا تبدیل کنید: `ffmpeg -i in.m4a -ac 1 -ar 16000 -c:a pcm_s16le out.wav`

## مراحل

از پوشهٔ `sedasanj/` (برای `speaker_eval.py`) و `jalase-negar/` (برای bench):

```bash
python scripts/speaker_eval.py validate test_data/speaker_eval/manifest.json
```

```bash
cd ../jalase-negar && BENCH_MODELS=~/.cache/jalase-bench/models BENCH_SPEAKER_SET=../sedasanj/test_data/speaker_eval BENCH_OUT=../sedasanj/test_data/speaker_eval/hypotheses BENCH_VARIANT=app-baseline flutter test test/bench/bench_speaker_test.dart
```

```bash
python scripts/speaker_eval.py score test_data/speaker_eval/manifest.json test_data/speaker_eval/hypotheses/app-baseline.json
```

### پیش‌نویس برچسب

اگر هنوز برچسب ندارید، یک `manifest.json` بدون فیلد `truth` فایل‌ها (یا با مسیر فایلِ هنوز ناموجود) بسازید، bench را یک بار اجرا کنید و:

```bash
python scripts/speaker_eval.py draft test_data/speaker_eval/manifest.json test_data/speaker_eval/hypotheses/app-baseline.json test_data/speaker_eval/truth_draft
```

فایل‌های `draft-<id>.json` و `draft-<id>.txt` ساخته می‌شوند. **با گوش دادن به صوت** نام‌ها و مرزها را اصلاح کنید و نتیجه را به `truth/<id>.json` ببرید. پیش‌نویس از خروجی خود مدل است؛ خطایی که پیش‌نویس و مدل هر دو دارند و از قلم بیفتد در امتیاز دیده نمی‌شود.

## تفسیر نتیجه

- `DER`: خطای جدا کردن گوینده‌ها (از دست رفتن گفتار، گفتار اضافه، اشتباه گرفتن). `id_accuracy`: سهم لحظه‌هایی که یک نفر تنها صحبت می‌کند و اپ نامش را درست گفته. `false_accept`: سهم لحظه‌هایی که اسم **اشتباه** داده شده (بدتر از «ناشناس» است). `false_reject`: سهم لحظه‌هایی که فرد ثبت‌نام‌شده «ناشناس» ماند.
- مقایسهٔ دو سیستم با `compare` روی بلوک‌های ۳۰ ثانیه‌ای و بازهٔ اطمینان ۹۵٪ انجام می‌شود. با چند جلسهٔ کم بازه پهن است: «کاملاً بهتر نیست» یعنی **نامشخص**، نه «بی‌اثر».
- اعداد روی Mac اند و چیزی دربارهٔ سرعت یا دقت روی گوشی نمی‌گویند.
