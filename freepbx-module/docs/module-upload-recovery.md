# بازیابی پنل پس از آپلود ماژول

## علائم

بعد از آپلود نسخه‌های `1.4.0` یا `1.5.0`، پنل خطای `stristr() expects parameter 1 to be string, array given` در `admin/bootstrap.php` نمایش می‌دهد. این تصویر به‌تنهایی توقف سرویس Asterisk را اثبات نمی‌کند.

## علت

تکرار `phpcomponent` در `module.xml` مقدار وابستگی را به آرایه تبدیل می‌کند. راه‌انداز FreePBX 16 آن را مستقیم به `stristr()` می‌دهد. نسخه `1.5.1` تنها یک ورودی دارد و تمام افزونه‌های ضروری PHP را هنگام نصب بررسی می‌کند؛ نبودن افزونه با `SS-DEP-1002` و دستور نصب مجدد گزارش می‌شود.

منابع رسمی: [راه‌انداز FreePBX 16](https://github.com/FreePBX/framework/blob/release/16.0/amp_conf/htdocs/admin/bootstrap.php)، [بررسی وابستگی‌ها](https://github.com/FreePBX/framework/blob/release/16.0/amp_conf/htdocs/admin/libraries/modulefunctions.class.php).

## راه‌حل

1. آرشیو `asterisk-module-1.5.1.zip` را در مسیر `/tmp` سرور PBX قرار دهید.
2. دستورات زیر را در نشست روت SSH اجرا کنید. ابتدا فقط فایل متادیتا پشتیبان‌گیری و صحت آن بررسی می‌شود؛ هیچ فایل هسته FreePBX تغییر نمی‌کند. در صورت خطا ادامه ندهید و فضای دیسک، مسیر آرشیو و دسترسی‌ها را بررسی کنید.

```bash
bash <<'RECOVERY'
set -euo pipefail
module=/var/www/html/admin/modules/recuploader
work=$(mktemp -d /tmp/sedasanj-metadata.XXXXXX)
trap 'rm -rf "$work"' EXIT
unzip -q /tmp/asterisk-module-1.5.1.zip recuploader/module.xml -d "$work"
test -f "$module/module.xml"
backup=$(mktemp -d /var/backups/sedasanj-metadata.XXXXXX)
chmod 700 "$backup"
cp -p "$module/module.xml" "$backup/module.xml"
cmp "$module/module.xml" "$backup/module.xml"
stage=$(mktemp "$module/.module.xml.XXXXXX")
trap 'rm -rf "$work"; rm -f "${stage:-}"' EXIT
cp -p "$module/module.xml" "$stage"
cat "$work/recuploader/module.xml" > "$stage"
mv -f "$stage" "$module/module.xml"
echo "Verified metadata backup: $backup/module.xml"
RECOVERY
```

3. پنل را دوباره باز کنید و آرشیو کامل `1.5.1` را از Module Admin آپلود و نصب کنید. مرحله قبل فقط متادیتا را جایگزین کرده است و جای نصب کامل نسخه جدید را نمی‌گیرد. نصب کامل مسیر پشتیبان‌گیری معمول ماژول را دارد.
4. اگر پنل همچنان همین خطا را دارد، خروجی خطای جدید و وضعیت ماژول را بررسی کنید؛ فایل `bootstrap.php` را ویرایش نکنید. برای مشکل مستقل تلفنی وضعیت سرویس را با دستور فقط‌خواندنی زیر بررسی کنید:

```bash
systemctl status asterisk --no-pager
```

## تأیید

پنل ورود باید بدون خطای آرایه باز شود؛ پس از نصب کامل، نسخه فایل‌ها و نسخه ثبت‌شده باید `1.5.1` باشند. یک تماس ورودی و یک تماس خروجی و ارسال ضبط آن‌ها را بررسی کنید. ماتریس بازیابی روی PBX واقعی: ⚠ needs lab confirmation.

## پیشگیری

تست `ModuleXmlTest.php` از انتشار وابستگی آرایه‌ای جلوگیری می‌کند؛ تست `RuntimeRequirementsTest.php` بررسی می‌کند که حذف ورودی‌های تکراری باعث پذیرش افزونه‌های PHP مفقود نشود. اگر صفحه خطا اطلاعات ورود را نمایش داده است، رمز ورود پنل را تغییر دهید و تصویر آن را به اشتراک نگذارید.
