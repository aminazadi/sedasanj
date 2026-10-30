# پلن جامع اتصال درگاه‌های پرداخت (زرین‌پال، زیبال، سپ، به‌پرداخت ملت)

وضعیت: پیاده‌سازی در همین تغییر انجام می‌شود. منابع: مستندات رسمی زرین‌پال (`zarinpal.com/docs`) و پیاده‌سازی مرجع
`shetabit/multipay` و `dizatech/*_ipg` برای سپ، به‌پرداخت و زیبال (مستندات رسمی این سه درگاه فقط پس از ورود به پنل
پذیرنده در دسترس است). هر ادعایی که تأیید نشده با «⚠ نیاز به تأیید آزمایشگاهی» علامت خورده است.

## ۱. وضعیت فعلی

- فقط زرین‌پال (`app/services/payments.py`)؛ تنظیمات در `platform_settings` با کلید `commerce.*`.
- پرداخت‌ها در دیتابیس هر سازمان (tenant) نگهداری می‌شوند: `orders`, `order_items`, `payment_attempts`, `refunds`,
  `credit_grants`, `ledger_entries`, `tenant_balance_cache`.
- شارژ اعتبار: `POST /v1/billing/credit-orders` (دقیقه × نرخ دقیقه‌ی پلن، یا بسته) ← `POST /v1/orders/{id}/pay` ← callback ←
  `fulfill_order` ← `grant_credit` (ثبت در دفتر کل و کش موجودی).
- ایرادهای موجود: خطای callback مستقیم به مرورگر کاربر JSON می‌دهد؛ وضعیت `pending_verification` با rollback از بین
  می‌رود؛ `authority` سراسری یکتاست؛ دوباره‌پرداخت تکراری حفاظت ندارد؛ جاروی خودکار تراکنش‌های معلق وجود ندارد؛
  آدرس API زرین‌پال قدیمی است (`api.zarinpal.com`).

## ۲. خلاصه‌ی مستندات هر درگاه

| | زرین‌پال | زیبال | سپ (سامان) | به‌پرداخت (ملت) |
|---|---|---|---|---|
| انتقال | REST/JSON | REST/JSON | REST/JSON | SOAP/XML |
| مبلغ | ریال (یا `currency=IRT`) | ریال | ریال | ریال |
| درخواست | `POST payment.zarinpal.com/pg/v4/payment/request.json` | `POST gateway.zibal.ir/v1/request` | `POST sep.shaparak.ir/onlinepg/onlinepg` با `action=token` | `bpPayRequest` |
| هویت | `merchant_id` (۳۶ نویسه) | `merchant` (sandbox: `zibal`) | `TerminalId` | `terminalId/userName/userPassword` |
| شناسه‌ی پرداخت | `authority` | `trackId` | `token` | `RefId` |
| ریدایرکت | GET `/pg/StartPay/{authority}` | GET `gateway.zibal.ir/start/{trackId}` | POST فرم `Token` به `/OnlinePG/OnlinePG` | POST فرم `RefId` به `startpay.mellat` |
| بازگشت | GET `Authority`,`Status=OK/NOK` | GET `success`,`status`,`trackId`,`orderId` | POST `State`,`Status`,`RefNum`,`ResNum`,`RRN`,`TraceNo`,`SecurePan` | POST `RefId`,`ResCode`,`SaleOrderId`,`SaleReferenceId`,`FinalAmount`,`CardHolderPan` |
| وریفای | `verify.json` (کد ۱۰۰/۱۰۱) | `/v1/verify` (`result` ۱۰۰، ۲۰۱=قبلاً) | `VerifyTransaction` با `RefNum`+`TerminalNumber` (`ResultCode` 0) | `bpVerifyRequest` سپس `bpSettleRequest` |
| استعلام | `inquiry.json` | `/v1/inquiry` ⚠ | همان VerifyTransaction (idempotent) ⚠ | `bpInquiryRequest` |
| برگشت | `reverse.json` (۳۰ دقیقه، نیاز IP) | ندارد در API ⚠ | `ReverseTransaction` ⚠ | `bpReversalRequest` ⚠ |
| تأیید خودکار | وریفای‌نشده خودکار برگشت می‌خورد | همین ⚠ | تا ۳۰ دقیقه وریفای نشود برگشت می‌خورد ⚠ | وریفای/ستل‌نشده برگشت می‌خورد ⚠ |
| محدودیت | حداقل ۱٬۰۰۰ تومان؛ حداکثر ۱۰۰ میلیون تومان (کد ‎-۴۱‎) | حداقل ۱٬۰۰۰ ریال | حداقل ۱٬۰۰۰ ریال | حداقل ۱٬۰۰۰ ریال |

نکات امنیتی مشترک: IP سرور و دامنه‌ی callback باید در پنل هر درگاه ثبت شود (زرین‌پال ‎-۱۰/‎-۱۴، به‌پرداخت ۴۲۱/۶۲). هیچ
پرداختی فقط با تکیه بر پارامترهای callback پذیرفته نمی‌شود؛ همیشه وریفای سرور‌به‌سرور و تطبیق مبلغ انجام می‌شود.

## ۳. معماری هدف

```
Order ─┬─ PaymentAttempt (gateway, token, order_ref, status, callback_json, settled_at …)
       └─ OrderItem(credit: دقیقه × نرخ دقیقه)

app/services/gateways/
  base.py        Gateway (ABC)، RedirectSpec، CallbackInfo، Verification، GatewayError
  zarinpal.py  zibal.py  saman.py  behpardakht.py
  registry.py    فهرست درگاه‌ها، ساخت adapter از تنظیمات
app/services/gateway_settings.py   تنظیمات هر درگاه (اسرار با Fernet رمز می‌شوند)
app/services/payments.py           initiate / handle_callback / settle / reconcile / refund
```

اصول:
1. مبالغ داخلی تومان؛ تبدیل به ریال فقط در lifecycle پرداخت (`amount_rial = toman × 10`).
2. هر تلاش پرداخت یک `order_ref` عددی یکتای سراسری دارد (زمان‌میلی‌ثانیه × ۱۰۰۰ + تصادفی) که برای `orderId` ملت،
   `ResNum` سپ و `orderId` زیبال استفاده می‌شود.
3. URL بازگشت: `/v1/payments/{gateway}/callback?token=<order token>&attempt=<attempt id>&t=<tenant id>`؛ هر سه بررسی می‌شوند.
4. callback هرگز JSON خطا به کاربر نمی‌دهد؛ همیشه با ریدایرکت ۳۰۳ به `/payment-result` می‌رود.
5. مراحل با commit مجزا: (الف) ذخیره‌ی callback و وضعیت `pending_verification` ← (ب) وریفای بانک + تکمیل سفارش
   + commit ← (ج) فقط ملت: `bpSettleRequest` + ثبت `settled_at`. خرابی در هر مرحله توسط جاروی دوره‌ای ترمیم می‌شود.
6. تکمیل سفارش idempotent است (قفل ردیف سفارش + کلید یکتای دفتر کل `credit-order:{id}`).
7. اگر سفارش قبلاً پرداخت شده و callback یک تلاش دیگر برسد، آن تلاش `superseded` می‌شود و وریفای نمی‌شود
   (بانک مبلغ را خودکار برمی‌گرداند ⚠)؛ در پنل ادمین هشدار می‌ماند.
8. جارو (`reconcile_pending`) هر دقیقه در `reconciler_cron`: تلاش‌های `redirected` قدیمی‌تر از ۱۰ دقیقه و
   `pending_verification` را استعلام/وریفای می‌کند؛ ستل‌های معوق ملت را تکرار می‌کند؛ بعد از ۲ ساعت بدون پرداخت، `expired`.

## ۴. فازها

| فاز | محتوا | خروجی |
|---|---|---|
| ۱ | مدل داده: مایگریشن `0062_payment_gateways` | ستون‌های جدید `payment_attempts`، ایندکس یکتای `(gateway, authority)`، وضعیت‌های جدید |
| ۲ | لایه‌ی adapter چهار درگاه + registry | کلاس‌ها و تست واحد با mock HTTP |
| ۳ | تنظیمات درگاه‌ها (رمزشده) + API ادمین (فهرست، ذخیره، تست اتصال) | `/v1/admin/commerce/gateways*` |
| ۴ | جریان پرداخت: initiate چند‌درگاهی، callback عمومی، تکمیل، جارو، برگشت/استرداد | `payments.py` بازنویسی‌شده |
| ۵ | API عمومی روش‌های پرداخت و پیش‌فاکتور شارژ (نرخ دقیقه) | `/v1/billing/payment-methods`, `/v1/billing/credit-quote` |
| ۶ | رابط ادمین: صفحه‌ی «درگاه‌های پرداخت»، ستون‌های جدید پرداخت‌ها | `PaymentGateways.tsx` |
| ۷ | رابط مشتری: انتخاب روش پرداخت فقط از درگاه‌های فعال، فرم شارژ بر اساس نرخ دقیقه، صفحه‌ی نتیجه | کامپوننت‌ها و تصاویر |
| ۸ | تصاویر: لوگوی چهار درگاه، تصاویر نتیجه (موفق/ناموفق/در انتظار) و پرداخت امن | SVG در `web/client/src/assets` و `web/admin/src/assets` |
| ۹ | تست، کد خطا، مستند راهنما، changelog، env/compose | تست‌ها، `docs/payment-gateways.md`، CHANGELOG |

## ۵. جدول تصمیم وضعیت‌ها

`PaymentAttempt.status`: `redirected` → (`canceled` | `pending_verification` → (`verified` | `failed`)) ، و `expired`،
`superseded`. `verified` در ملت تا ثبت `settled_at` «ستل‌نشده» است و جارو آن را تکرار می‌کند.

| رویداد | نتیجه |
|---|---|
| Status=NOK / ResCode≠0 / success=0 / State≠2 | `canceled` یا `failed` (بر اساس کد)، سفارش `pending_payment` می‌ماند تا کاربر دوباره تلاش کند |
| مبلغ بازگشتی با سفارش نمی‌خواند | `failed` با `failure_code=amount_mismatch` + برگشت بانکی (در درگاه‌هایی که پشتیبانی می‌کنند) |
| خطای شبکه هنگام وریفای | `pending_verification` (commit شده)؛ جارو دوباره تلاش می‌کند |
| وریفای موفق ولی commit تکمیل شکست | وریفای دوباره idempotent است (زرین‌پال ۱۰۱، ملت ۴۳، زیبال ۲۰۱) و جارو ترمیم می‌کند |
| پرداخت دوباره‌ی سفارش پرداخت‌شده | `superseded` + هشدار ادمین |

## ۶. مالی

- شارژ: `دقیقه × نرخ دقیقه‌ی مؤثر` در `create_credit_order`؛ در `fulfill_order` ثانیه‌ها به `credit_grants` و ردیف
  `credit_purchase` در `ledger_entries` و کش موجودی اضافه می‌شود (تومان = مبلغ سفارش).
- استرداد: ثبت `refunds` + ردیف منفی دفتر کل؛ روش `reverse` فقط برای درگاه‌های دارای قابلیت برگشت؛ سایر موارد `manual`.
- فاکتور: به‌ازای هر سفارش پرداخت‌شده یک `invoices` (موجود).
- حسابرسی: `payment.initiated`, `payment.verified`, `payment.failed`, `payment.reconciled`, `gateway.settings_changed` (بدون اسرار).

## ۷. موارد «⚠ نیاز به تأیید آزمایشگاهی»

1. نام‌های دقیق فیلد پاسخ `ReverseTransaction` سپ و پنجره‌ی زمانی برگشت.
2. فضای‌نام SOAP ملت (`http://interfaces.core.sw.bps.com/`) و نام فیلدهای `bpInquiryRequest`.
3. وجود/نام endpoint استعلام زیبال (`/v1/inquiry`) و برگشت زیبال از API.
4. زمان برگشت خودکار تراکنش‌های وریفای‌نشده در هر چهار درگاه.
5. محدودیت IP/دامنه در محیط عملیاتی هر درگاه (ثبت در پنل هر پذیرنده).
تا تأیید، این مسیرها با خطای شفاف و بدون تغییر وضعیت مالی شکست می‌خورند و کاربر/ادمین گام بعدی را می‌بیند.

## ۸. تست و پذیرش

واحد (mock HTTP): ساخت درخواست، تبدیل ریال، parse callback، تطبیق مبلغ، کدهای خطا، SOAP ملت، مراحل وضعیت،
جاروی معوق، یکتایی `order_ref`. ایستا: `ruff`, `mypy apps`, `pytest`, `npm run build` برای دو وب‌اپ.
آزمون زنده (توسط اپراتور): sandbox زرین‌پال، merchant `zibal` زیبال، و ترمینال آزمایشی سپ/ملت با IP ثبت‌شده.
