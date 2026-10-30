# پلن‌ها، اشتراک‌ها و صورت‌حساب

این سند چرخهٔ حیات پلن و اشتراک در صداسنج را توضیح می‌دهد. کدها، مسیرها و نام ستون‌ها انگلیسی و LTR هستند.

## مدل داده

`Plan` (کد، نام، پرچم‌های `active`, `public`, `sellable`, `is_trial`) ← `PlanVersion` (قیمت و سهمیه‌ها؛ منتشرشده تغییر نمی‌کند) ← `Subscription` (عکس لحظهٔ خرید از نسخه). تغییر قیمت یعنی نسخهٔ جدید؛ مشترکان فعلی روی نسخهٔ خودشان می‌مانند (`commerce.renewal_price_policy`: `keep` یا `latest`).

- پرداخت فقط **سالانه** است. پلن `demo` آزمایشی است (`is_trial`) و قابل خرید نیست (`sellable = false`).
- همهٔ مبالغ تومان و `bigint` هستند. مالیات (`commerce.tax_percent`، پیش‌فرض ۰) ردیف جداگانهٔ `tax` در سفارش است و روی `Invoice` به‌صورت `net_toman`, `tax_toman`, `tax_percent`, `lines` ذخیره می‌شود.

## وضعیت اشتراک

تنها مالک تغییر `status` ماژول `app/services/subscription_state.py` است.

| وضعیت | معنی |
|---|---|
| `pending_payment` | ثبت‌نام پولی پرداخت‌نشده؛ بعد از `commerce.payment_window_days` (۷) منقضی می‌شود |
| `trialing` | آزمایشی؛ پایان با `trial_days` همان نسخه |
| `active` | فعال و پرداخت‌شده |
| `grace` | **ذخیره نمی‌شود**؛ بعد از `period_end` تا `commerce.grace_days` (۳) سرویس کار می‌کند |
| `expired` | پایان یافته (cron) |
| `canceled` | لغو یا توقف توسط ادمین |

انتخاب اشتراک جاری: اولویت `active` > `trialing` > `pending_payment` > `expired` > `canceled`. خواندن entitlement هرگز چیزی نمی‌نویسد.

## تغییر پلن

- خرید پلن دیگر روی اشتراک پولی در جریان ممنوع است (`subscription_exists`). تغییر فقط با `POST /v1/subscription/change` (هدر `Idempotency-Key` اجباری و وابسته به محتوای درخواست).
- **ارتقا:** مبلغ تفاضل به نسبت باقی‌ماندهٔ سال پرداخت‌شده؛ بعد از پرداخت پلن عوض می‌شود، تغییر `applied` می‌شود و دقیقهٔ اضافهٔ دورهٔ جاری به نسبت زمان باقی‌مانده داده می‌شود. بازپرداخت کامل ارتقا پلن و اپراتورها را برمی‌گرداند و دقیقهٔ استفاده‌نشدهٔ آن را پس می‌گیرد.
- **تنزل / هم‌قیمت:** در `period_end` اعمال می‌شود (`scheduled`)؛ با `POST /v1/subscription/changes/{id}/cancel` قابل لغو است. درخواست جدید تغییرهای باز قبلی را لغو می‌کند.
- **تمدید زودهنگام همان پلن:** یک سال به انتهای دوره اضافه می‌شود و `period_start` (سالگرد) ثابت می‌ماند.
- **لغو:** `POST /v1/subscription/cancel-at-period-end` و `…/resume` (فعال و آزمایشی).

## دقیقه و سهمیه

یک «ماه سهمیه» برای دقیقه و پیام دستیار: ماه سالگرد شروع اشتراک (`services/quotas.quota_period_start`). دقیقهٔ پلن یک‌بار در هر پنجره با کلید `plan-credit:{subscription}:{window}` داده می‌شود (`services/plan_credit.py`)، در پایان پنجره منقضی می‌شود و قبل از هر رزرو، دقیقهٔ منقضی از موجودی کم می‌شود. مصرف: اول دقیقهٔ پلن، بعد اعتبار پیش‌خریدی. اعتبار پیش‌خریدی منقضی نمی‌شود. پیام دستیار: `reserved` و `succeeded` شمرده می‌شوند و `assistant_source_limit` اعمال می‌شود.

## تمدید و اعلان

cron هر دقیقه (`reconciler_cron`): انقضا، سفارش تمدید (`renewal_lead_days` قبل)، ایمیل‌های اعلان، تطبیق پرداخت. هر بخش جدا از دیگری خطا می‌خورد و شکست یک سازمان بقیه را متوقف نمی‌کند. اعلان‌ها (`renewal_due` در ۷ و ۱ روز، `trial_ending` در ۲ روز، `grace_started`, `subscription_expired`) در `notification_log` ثبت می‌شوند و برای هر دوره یک‌بار می‌روند؛ ارسال ناموفق تا ۳ بار تکرار می‌شود. پیامک هنوز نیست (به قالب‌های SMS.ir نیاز دارد).

## کاتالوگ (ادمین)

انتشار: قیمت پلن قابل‌فروش > ۰، `trial_days` برای آزمایشی، `effective_at` نه در گذشته، و نسخهٔ منتشرشدهٔ قبلی بازنشسته می‌شود. بازنشستهٔ تنها نسخهٔ پلن فعال نیاز به `force` دارد (`plan_in_use`). ویرایش پلن `reason` می‌خواهد و `demo`/`legacy_custom` غیرفعال نمی‌شوند.

## تنظیمات ادمین (`platform_settings`, پیشوند `commerce.`)

`tax_percent`, `grace_days`, `payment_window_days`, `order_ttl_days`, `renewal_price_policy`, `renewal_lead_days`, `max_order_toman`, `credit_min_minutes`, `credit_max_minutes`, `credit_presets`, `featured_plan_code`, `default_price_per_minute_toman`.

## کدهای خطا

`subscription_exists`, `change_conflict`, `plan_not_sellable`, `plan_in_use`, `plan_code_exists`, `order_amount_too_large` (۴۰۹/۴۲۲)، `subscription_inactive` و `insufficient_credit` و `quota_exceeded` (۴۰۲؛ agent فقط وضعیت ۴۰۲ را می‌بیند). هر کد صفحهٔ راهنما دارد: `/help/errors/<code>` (migration `0069_billing_help_content`).

## آنچه آزمایش نشده

تست‌های PostgreSQL با کاربر superuser اجرا شده‌اند، پس RLS در آن‌ها اعمال نمی‌شود (فیلتر `tenant_id` صریح است). درگاه‌های واقعی، ارسال واقعی ایمیل/پیامک و اجرای UI در مرورگر آزمایش نشده‌اند.
