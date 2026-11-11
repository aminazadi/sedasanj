# ساخت نسخه‌های انتشار جلسه‌نگار

همهٔ دستورها از ریشهٔ مخزن اجرا می‌شوند. خروجی‌ها در `jalase-negar/dist/<نسخه>/` ذخیره می‌شوند و در گیت نمی‌روند.

```bash
scripts/build-jalase-negar-release.sh all      # اندروید + iOS + مک
scripts/build-jalase-negar-release.sh android  # فقط اندروید
```

متغیر `STORE` (با `--dart-define=STORE=…`) کانال توزیع را مشخص می‌کند: `direct`، `bazaar`، `myket`، `sibapp`، `anardooni` یا `desktop`. فقط نسخهٔ `direct` اندروید خودش را به‌روزرسانی می‌کند؛ در بقیه کارت «به‌روزرسانی» تنظیمات پنهان است و فروشگاه نسخهٔ جدید را می‌رساند.

## اندروید: مستقیم، بازار، مایکت

| فایل | کانال | به‌روزرسانی درون‌برنامه‌ای |
| --- | --- | --- |
| `JalaseNegar-direct-v<نسخه>.apk` | سرور خودمان | دارد (`REQUEST_INSTALL_PACKAGES`) |
| `JalaseNegar-bazaar-v<نسخه>.apk` | کافه‌بازار | ندارد |
| `JalaseNegar-myket-v<نسخه>.apk` | مایکت | ندارد |

- امضا از `~/.sedasanj-secrets/jalase-negar/key.properties` (یا مسیر `JALASE_KEY_PROPERTIES`) خوانده می‌شود. بدون آن، بیلد منتشرشدنی نیست و اسکریپت متوقف می‌شود. کلید و رمز را در گیت یا چت نگذارید.
- هر سه نسخه `applicationId` و گواهی امضای یکسان دارند. پس از بیلد، نبودن مجوز نصب بسته در نسخه‌های فروشگاهی را بررسی کنید: `aapt2 dump permissions <apk> | grep INSTALL_PACKAGES` باید خالی باشد.
- ⚠ نیاز به تأیید در پنل فروشگاه: پذیرش APK با کلید امضای خودمان و سقف حجم/معماری. نسخه فقط `arm64-v8a` است (مدل شنوا).

## iOS: سیب‌اپ و اناردونی

بیلد iOS بدون گواهی اپل انجام می‌شود (فلاتر فقط پروژه را آماده می‌کند و `xcodebuild archive` با غیرفعال‌بودن امضا آرشیو می‌سازد؛ `flutter build ipa --no-codesign` در مرحلهٔ «Development Team» متوقف می‌شود) و دو خروجی دارد: `JalaseNegar-v<نسخه>.xcarchive` و `JalaseNegar-unsigned-v<نسخه>.ipa`.

- **سیب‌اپ:** طبق [مقالهٔ زومیت دربارهٔ SibApp Export](https://www.zoomit.ir/tech-iran/410578-sib-app-export) (مهر ۱۴۰۲) ابزار SibApp Export از آرشیو Xcode فایل IPA مناسب استورهای ادهاک می‌سازد و آن را در پنل توسعه‌دهندهٔ سیب‌اپ بارگذاری می‌کنید. ⚠ مقاله حدود سه سال قدمت دارد؛ روش فعلی را از پنل سیب‌اپ تأیید کنید.
- **اناردونی:** مستندات عمومی پیدا نشد؛ پنل `developer.anardoni.com` پشت ورود است. ⚠ نوع فایل (IPA امضاشده یا بدون امضا) و قوانین بررسی را از پنل یا پشتیبانی اناردونی بپرسید.
- حداقل iOS برابر `IPHONEOS_DEPLOYMENT_TARGET` پروژه است. شناسهٔ بسته: `app.jalasenegar.jalaseNegar`.
- `ios/Podfile` نام فریم‌ورک `sherpa-onnx` را به `SherpaOnnxC` اصلاح می‌کند؛ بدون آن لینک و embed شکست می‌خورد. بعد از ارتقای `sherpa_onnx` بررسی کنید هنوز لازم است.
- بیلد iOS به نصب «iOS platform» در Xcode نیاز دارد (`xcodebuild -downloadPlatform iOS`).

## مک

`JalaseNegar-macos-v<نسخه>.dmg` (پنجرهٔ نصب با پس‌زمینهٔ صداسنج و کشیدن به Applications؛ با `scripts/make-jalase-negar-dmg.sh`) و `…zip` شامل `Jalase-Negar.app` هستند. ساخت DMG به یک نشست دسکتاپ نیاز دارد، چون Finder چیدمان را با AppleScript می‌چیند. برنامه sandbox است و مجوز میکروفون، دوربین (اسکن QR)، شبکه و انتخاب فایل را دارد. امضای Developer ID و notarization هنوز انجام نشده است، پس مک روی دستگاه دیگر هشدار Gatekeeper می‌دهد (راست‌کلیک ← Open). ⚠ برای انتشار عمومی گواهی Developer ID لازم است.

## ویندوز

ویندوز روی مک ساخته نمی‌شود. workflow `.github/workflows/jalase-negar-windows.yml` را در GitHub Actions اجرا کنید (Run workflow، یا تگ `jalase-negar-v<نسخه>`)؛ خروجی‌ها در Artifacts هستند: نصب‌کنندهٔ `JalaseNegar-Setup-v<نسخه>.exe` (Inno Setup، اسکریپت `windows/installer/jalase_negar.iss`، با تصاویر برند) و zip پرتابل. زمان‌اجرای Visual C++ کنار برنامه بسته می‌شود. ⚠ این workflow هنوز اجرا نشده و روی ویندوز واقعی آزمایش نشده است.

محدودیت‌های دسکتاپ: اسکن QR در ویندوز نیست (از فایل کانفیگ یا متن چسبانده‌شده استفاده کنید)؛ سرویس پیش‌زمینه و به‌روزرسانی خودکار فقط روی اندروید هستند؛ پایگاه داده در ویندوز با `sqflite_common_ffi` کار می‌کند.

آیکن‌ها و تصاویر نصب‌کننده با `scripts/generate-jalase-negar-icons.py` و `swift scripts/generate-jalase-negar-installer-art.swift` از هندسهٔ لوگو ساخته می‌شوند، نه از بزرگ‌کردن favicon ۶۴ پیکسلی.
