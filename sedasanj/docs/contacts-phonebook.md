# Phonebook (دفترچه تلفن)

Per-organisation contacts used to label callers: the contact's title is shown above the number in
the calls table and in the call detail header (`caller_name` / `dialed_name` on `CallSummary`).

## Behaviour

- Table `contacts` (migration `0057_contacts`): one row per phone number, unique per tenant, RLS like
  every tenant table. Numbers are stored normalised (`normalize_call_number`), so `+98912…`,
  `0098912…`, `0912…` and Persian digits all match the same contact.
- API (`routers/contacts.py`): `GET /v1/contacts` (all signed-in users, read-only for operators),
  `POST/PATCH/DELETE` and `POST /v1/contacts/import`, `GET /v1/contacts/export|template`
  (organisation admins only; import/export/delete are audited).
- CSV import: UTF-8 (with or without BOM), UTF-16 or Windows-1256; comma, semicolon or tab; first row
  is the header (Persian or English names, see `_HEADER_ALIASES`); required columns: name and phone.
  Limits: 5 MB, 20 000 rows. `dry_run=true` returns the report without saving. `mode=skip` keeps
  existing contacts, `mode=update` overwrites only the cells that are filled. Row errors are reported
  with their line number; the first row wins when a number appears twice in one file.
- CSV export: UTF-8 with BOM (Excel shows Persian correctly); text cells starting with `= + - @` get a
  leading `'` (spreadsheet formula injection guard) which import removes again.

## Province and city

- Columns `province` / `city` (migration `0059_contact_geo`); a city requires a province.
- Data: `app/data/iran_geo.json` (31 provinces, 1,323 cities) built from the MIT `iran-cities-json@2.0.0`
  package by `scripts/build_iran_geo.py` (names normalised to Persian ی/ک, "و" respaced, Persian alphabetical
  order). `GET /v1/contacts/geo` serves it to the form drop-downs.
- Only listed names are accepted (form and import). The upstream list does not contain every small town;
  to add one, edit the JSON (or the source package) and rebuild.

## Help-center article (Persian, to publish from the admin panel)

**عنوان:** ایمپورت و خروجی گرفتن از دفترچه تلفن

**علائم:** شماره‌ها در تماس‌ها بدون نام نمایش داده می‌شوند، یا ایمپورت فایل با خطا متوقف می‌شود.

**روش کار:**

1. از «دفترچه تلفن» دکمهٔ «ایمپورت CSV» و سپس «دریافت فایل نمونه» را بزنید.
2. فایل را در اکسل پر کنید. ردیف اول باید عنوان ستون‌ها باشد: نام، شماره تلفن، شرکت، ایمیل، توضیحات
   (فقط نام و شماره الزامی است). استان و شهر باید دقیقاً مطابق فهرست استان‌ها و شهرهای ایران باشند؛ شهر بدون استان پذیرفته نمی‌شود.
3. از منوی Save As گزینهٔ **CSV UTF-8** را انتخاب کنید.
4. فایل را بارگذاری و «بررسی فایل» را بزنید؛ گزارش ردیف‌های جدید، به‌روز، تکراری و دارای خطا نمایش
   داده می‌شود و هنوز چیزی ذخیره نشده است. سپس «ثبت در دفترچه تلفن» را بزنید.

**خطاهای رایج:**

- «شماره به شکل علمی (E+) ذخیره شده»: ستون شماره را در اکسل به قالب Text تبدیل و دوباره وارد کنید.
- «ردیف اول باید عنوان ستون‌ها باشد…»: عنوان ستون‌های نام و شماره تلفن را مطابق فایل نمونه بگذارید.
- «رمزگذاری فایل شناسایی نشد»: فایل را با گزینهٔ CSV UTF-8 دوباره ذخیره کنید.
- اگر اکسل صفر ابتدای شماره را نشان نداد مشکلی نیست؛ ایمپورت هر دو حالت را می‌پذیرد.

**اطمینان از نتیجه:** در «تماس‌ها» عنوان مخاطب باید بالای شماره‌اش دیده شود.

## راهنمای انتخاب مخاطب و اپراتور داخلی

در صفحهٔ «داخلی‌ها»، کادر مخاطب یا اپراتور را باز کنید و نام، شماره یا ایمیل را جستجو کنید.
فهرست روی ردیف‌های جدول نمایش داده می‌شود و اگر پایین صفحه جا نباشد، بالای کادر باز می‌شود.
با کلیدهای جهت‌دار و Enter انتخاب کنید؛ برای بستن فهرست Escape بزنید یا بیرون آن کلیک کنید.
پس از انتخاب، نام باید در همان ردیف دیده شود. اگر ثبت انجام نشد، پیام خطا را بررسی و دوباره تلاش کنید.
