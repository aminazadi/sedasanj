# مجموعهٔ طلایی ASR (Golden set)

این پوشه فقط راهنما و نمونهٔ manifest را نگه می‌دارد. **صوت، متن مرجع واقعی و خروجی سیستم‌ها هرگز commit نمی‌شوند** (در `.gitignore` هستند): ممکن است داده‌ی مشتری باشند.

## ساختار محلی

```
test_data/asr_golden/
  manifest.json            # شامل clips (از manifest.example.json بسازید)
  audio/<id>.wav           # PCM16، mono، 16kHz (یا 8kHz برای کلیپ تلفنی)
  hypotheses/<system>.json # {"<id>": "متن"}
```

## معیار انتخاب کلیپ (۲۰ تا ۴۰ کلیپ)

- هر کلیپ ۳۰ تا ۱۲۰ ثانیه؛ فقط صوتی که مجوز استفاده دارد؛ نام، شماره و اطلاعات شخصی حذف یا ناشناس شده باشد.
- پوشش `tags`: `meeting` (جلسه)، `phone-8k` (تلفنی)، `quiet` (گفتار آرام یا دور از میکروفن)، `noisy` (پرنویز)، `clean`، `overlap` (هم‌پوشانی گوینده)، `numbers` (عدد و تاریخ)، `long` (بیش از ۱۰ دقیقه، حداقل ۲ کلیپ).
- متن مرجع را انسان بنویسد؛ خروجی خود ASR را بدون بازبینی مرجع نکنید.

## گرفتن خروجی هر سیستم

1. **Baseline A: سرور (CPU، INT8).** همه کلیپ‌ها را به aiservice بدهید و فقط متن را ذخیره کنید:
   ```bash
   curl -sS -H "Authorization: Bearer $ASR_API_KEY" \
     -F model=shenava-koochik-v1-5-rnnt -F language=fa -F ensure_timestamps=true \
     -F response_format=verbose_json -F file=@audio/clip01.wav \
     "$ASR_URL/v1/audio/transcriptions"
   ```
   پاسخ `202` است؛ نتیجه را از `Location: /v1/tasks/{id}` و `/result` بگیرید و `text` را در `hypotheses/server-cpu-int8.json` بگذارید. کلید API را در shell history یا گزارش ننویسید.
2. **Baseline B: اپ فعلی.** خروجی رونویسی لوکال جلسه‌نگار را برای همان کلیپ‌ها به `hypotheses/app-current.json` ببرید (ابزار export در فاز ۴ ساخته می‌شود؛ تا آن موقع دستی از جزئیات جلسه).
3. نام سیستم = نام فایل بدون پسوند.

## اجرا

```bash
cd sedasanj
python scripts/asr_eval.py score test_data/asr_golden/manifest.json \
  test_data/asr_golden/hypotheses/server-cpu-int8.json \
  test_data/asr_golden/hypotheses/app-current.json
python scripts/asr_eval.py compare test_data/asr_golden/manifest.json \
  test_data/asr_golden/hypotheses/server-cpu-int8.json \
  test_data/asr_golden/hypotheses/app-candidate.json --max-delta 0.02
```

اگر برای کلیپی خروجی نباشد اسکریپت خطا می‌دهد (WER را با کلیپ جاافتاده مقایسه نمی‌کند). آستانهٔ نهایی ۲٪ پس از ثبت Baseline تأیید می‌شود.
