# ۰۷ — داده و حالت‌ها در همهٔ سطوح (واژه‌نامه، enumها، خطاها، الگوی حالت‌ها)

## هدف

این صفحه مرجع واحد برای طراح یا ابزار هوش مصنوعی طراحی (Claude Design) است تا در همهٔ سطوح (پنل سازمان، پنل ادمین، اپ جلسه‌نگار، ماژول FreePBX) از «چیزها» و «حالت‌ها» یک زبان مشترک استفاده کند: هر موجودیت چه فیلدهایی در رابط نشان می‌دهد، هر مقدار enum دقیقاً چه نام انگلیسی و چه برچسب فارسی دارد، نشان وضعیت چه نقشی دارد، پیام‌های خطا چه می‌گویند و برای بارگذاری/خالی/خطا/عدم‌دسترسی/در حال پردازش/آفلاین کدام مؤلفه‌ها موجودند.

## راهنمای برچسب‌ها

| برچسب | معنی |
| --- | --- |
| «موجود» | در کد امروز وجود دارد و خوانده شده است. |
| «جدید» | پیشنهاد بازطراحی؛ امروز وجود ندارد. |
| «جدید (نیازمند بک‌اند)» | به API/فیلد تازه نیاز دارد. |
| «⚠ نیازمند تأیید» | در کد تأیید نشده، یا بین دو منبع ناسازگاری دیده شده است. |

قرارداد: متن فارسی؛ شناسه‌ها، مسیرها، کدهای خطا و مقدارهای enum به انگلیسی در بک‌تیک (LTR، رقم لاتین). **نقش نشان** (badge role) فقط یکی از `success`، `warning`، `danger`، `info`، `neutral` است و رنگ تعیین نمی‌کند. ستون «تُن در کد» نام کلاس واقعی وب (`badge-<tone>`) است؛ دو تُن `violet` و `orange` در وب هست که در مجموعهٔ نقش‌ها نیست و به نزدیک‌ترین نقش نگاشت شده‌اند (`violet`→`info` برای «هوش مصنوعی در حال کار»، `orange`→`warning` برای «خطای قابل تکرار/حساس»).

## منابع کد

| موضوع | مسیر |
| --- | --- |
| مدل‌ها و قیدهای CHECK | `sedasanj/apps/api/app/models.py` |
| قالب خطا و کدهای API | `sedasanj/apps/api/app/errors.py` (`ERROR_STATUS`، `RETRYABLE_CODES`) |
| اسکیماها | `sedasanj/apps/api/app/schemas.py` |
| تحلیل صورت‌جلسه | `sedasanj/apps/api/app/services/meeting_minutes.py` |
| کارها | `sedasanj/apps/api/app/services/follow_up_tasks.py`، `routers/tasks.py` |
| scopeهای API | `sedasanj/apps/api/app/services/api_scopes.py` |
| برچسب‌ها و تُن‌ها در پنل | `sedasanj/web/client/src/api.ts`، `components/Widgets.tsx`، `components/MeetingStatusBadge.tsx`، `components/SubscriptionPanel.tsx`، `pages/Account.tsx`، `pages/Tasks.tsx`، `auth.tsx` |
| برچسب‌ها در پنل ادمین | `sedasanj/web/admin/src/pages/Commerce.tsx`، `Subscriptions.tsx`، `ModuleReleases.tsx`، `JalaseNegarReleases.tsx`، `ModelReleases.tsx`، `Installations.tsx` |
| پیام‌های خطای فارسی | `sedasanj/web/client/src/lib/billingErrors.mjs`، `lib/taskErrors.ts`، `components/EditOrganizationUser.tsx` |
| مؤلفه‌های مشترک | `sedasanj/web/shared/components/` (`Skeleton.tsx`، `PaginatedTable.tsx`، `FilterBar.tsx`، `JalaliDatePicker.tsx`، `ToggleSwitch.tsx`، `PageSizeSelect.tsx`، `ReleaseTimeline.tsx`)، `sedasanj/web/shared/lib/` (`useResource.ts`، `resourceState.ts`) |
| مؤلفه‌های پنل | `sedasanj/web/client/src/components/` (`PanelEmpty.tsx`، `BrandLoader.tsx`، `Toast.tsx`، `ConfirmDialog.tsx`، `FormDialog.tsx`، `ProcessingIndicator.tsx`، `ProcessingTimeline.tsx`، `OverflowMenu.tsx`، `Widgets.tsx`) |
| کدهای ماژول FreePBX | `sedasanj/apps/api/app/data/module_error_codes.json`، `skills/sedasanj-error-codes/SKILL.md` |
| کدهای اپ | `jalase-negar/lib/` (جست‌وجوی `JN-`)، `jalase-negar/README.md` |
| قواعد پروژه | `AGENTS.md` (قاعدهٔ ۱۰ و بخش زبان) |

---

## ۱. واژه‌نامهٔ موجودیت‌ها (موجود)

«فیلدهای قابل‌نمایش» آنچه رابط معمولاً نشان می‌دهد است، نه همهٔ ستون‌ها. نام جدول/فیلد انگلیسی است.

### سازمان و افراد

| موجودیت | جدول/نوع | فیلدهای قابل‌نمایش | یادداشت |
| --- | --- | --- | --- |
| سازمان (tenant / organization) | `tenants` | `name`، `status`، `timezone` (پیش‌فرض `Asia/Tehran`)، `locale` (`fa`)، `max_operators`، `audio_retention_days`، `operator_ranking_visible`، `created_at` | هر سازمان پایگاه‌داده جدا دارد (`tenant_database_registry`) |
| کاربر (user) | `users` | `email`، `display_name`، `role`، `mobile_number`، `extension`، `is_primary_admin`، `panel_permissions`، `created_at` | `role`: `org_admin`/`operator`/`viewer`. مدیر اصلی (`is_primary_admin`) محافظت‌شده است |
| اپراتور (operator) | `users` با `role = operator` + `call_operator_assignments` | نام، داخلی، امتیاز و مربی‌گری (score/coaching) | «اپراتور» نقش کاربر است؛ نسبت‌دهی تماس به اپراتور با داخلی انجام می‌شود (`assignment_source`، `confidence`) |
| داخلی (extension) | `pbx_extensions` | `extension` (`^[0-9*#]{1,20}$`)، `pbx_name`، `active`، `contact_name`، `user_name`، `owner_conflict`، `synced_at` | از مرکز تلفن همگام می‌شود |
| مخاطب (contact) | `contacts` | `name`، `phone_number` (۳ تا ۱۵ رقم، نرمال‌شده)، `company`، `email`، `province`، `city`، `notes` | شهر بدون استان مجاز نیست (`contacts_city_province_check`) |
| دستگاه متصل (جلسه‌نگار) | `api_keys` با `kind = mobile` | `label`، `token_prefix`، `last_used_at`، `created_at`، `revoked_at` | فقط scope `meetings:write` |

### تماس و تحلیل

| موجودیت | جدول/نوع | فیلدهای قابل‌نمایش | یادداشت |
| --- | --- | --- | --- |
| تماس (call) | `calls` | `caller_number`، `dialed_number`، `caller_name`، `direction`، `agent_extension`، `call_type`، `started_at`، `duration_ms`، `status`، `progress_pct`، `progress_detail`، `error_code`، `billed_seconds` | `status` مراحل پردازش؛ `call_type` نتیجهٔ تلفنی |
| پیام‌گیر صوتی (voicemail) | `calls` با `call_type = voicemail` | `voicemail_context`، `voicemail_folder`، `voicemail_message_id` + همهٔ فیلدهای تماس | نمای «پیام‌گیر» همان فهرست تماس با فیلتر ثابت است |
| متن (transcript) | `transcripts` | `full_text`، `corrected_text`، `corrected_at`، `asr_model`، `asr_version` + `utterances` (`channel` ۰ یا ۱، زمان، متن) | نسخه‌های تصحیح/ASR جدا (`transcript_revisions`، `asr_transcript_revisions`) |
| تحلیل (analysis) | `analysis_runs` | `llm_model`، `prompt_version`، `status`، `created_at` | `AnalysisStep.kind`: `map`/`reduce`/`extract`/`repair`؛ `status`: `queued`/`submitted`/`polling`/`succeeded`/`failed` |
| بینش (insight) | `call_insights` | `summary`، `keywords[]`، `sentiment`، `sentiment_score`، `intent`، `topics[]`، `ner`، `action_items` | — |
| بینش فروش | `sales_insights` | `funnel_stage`، `outcome`، `certainty`، `confidence` (۰ تا ۱)، `product`، `objections[]`، `win_loss_reason`، `next_action`، `next_action_due_at`، `evidence[]` | — |
| امتیاز (score) | `operator_call_scores` | `operator_label`، `total_score`، `criteria_scores[]` (`title`، `description`، `weight`)، `status`، `error_detail` | `status` پیش‌فرض `queued`؛ ⚠ نیازمند تأیید: فهرست کامل مقدارها در مدل CHECK نیست |
| مربی‌گری | `operator_call_coachings` | `narrative`، `status`، `result` | — |
| کار پیگیری (task) | `follow_up_tasks` | `title`، `description`، `status`، `priority`، `due_date`، `assignee_name`، `source_phone`، `origin`، `is_overdue`، `version` | به **تماس** وصل است (`call_id` الزامی)، نه جلسه |
| جلسه (meeting) | `meetings` | `title`، `status`، `started_at`، `duration_ms`، `speaker_count`، `progress_pct`، `progress_detail`، `error_code`، `input_kind` (`audio`/`text`)، `owner_name`، `audio_available` | دیدنی برای مالک و `org_admin` |
| گوینده جلسه | `meeting_speakers` | `speaker_idx`، `label`، `user_id`، `total_ms` | برچسب پیش‌فرض «گوینده <n+1>» |
| بخش گفتار جلسه | `meeting_segments` | `t_start_ms`، `t_end_ms`، `speaker_idx`، `text`، `overlap`، `speaker_confidence` | `source`: `server_asr`/`device_asr` |
| صورت‌جلسه | `meeting_minutes` | `version`، `content_md`، `structured` (`summary`، `decisions`، `action_items`، `attendees`، `agenda`، `discussion`، `open_issues`)، `model`، `provider`، `is_selected` | چند نسخه برای هر جلسه |
| حاضر جلسه | `meeting_attendees` | `name`، `profile_client_id` | از اپ |
| فرد/ردصدا | `speaker_profiles`، `speaker_voiceprints` | `display_name`، `visibility` (`private`/`org`)، `consent_at`، `quality`، `dim` | همگام با اپ |

### مالی و اشتراک

| موجودیت | جدول/نوع | فیلدهای قابل‌نمایش | یادداشت |
| --- | --- | --- | --- |
| پلن (plan) | `plans` + `plan_versions` | `name`، `code`، `monthly_price_toman`، `annual_price_toman`، `base_operators`، `intro_minutes`، `overage_price_per_minute_toman`، `assistant_monthly_messages`، `trial_days`، `status` | نسخه‌ها `draft`/`published`/`retired` |
| اشتراک (subscription) | `subscriptions` | `status`، `billing_period`، `period_start`، `period_end`، `cancel_at_period_end`، `extra_operators`، `plan_name` | در UI وضعیت مشتق «grace» (در مهلت تمدید) هم دیده می‌شود |
| تغییر اشتراک | `subscription_changes` | `status` | مقدارها: `scheduled`/`pending_payment`/`applied`/`canceled`/`failed` |
| سفارش (order) | `orders` | `number`، `kind`، `status`، `amount_toman`، `customer_name`، `created_at`، `paid_at` | |
| تلاش پرداخت | `payment_attempts` | `gateway`، `status`، `amount_rial`، `ref_id`، `failure_code`، `verified_at` | مبلغ سفارش تومان؛ تلاش پرداخت ریال |
| فاکتور (invoice) | `invoices` | `number`، `amount_toman`، `net_toman`، `tax_toman`، `tax_percent`، `lines[]`، `issued_at` | |
| بازپرداخت | `refunds` | `amount_toman`، `status` (`pending`/`completed`/`failed`)، `method` (`reverse`/`manual`) | |
| اعتبار/کیف (credit / wallet) | `credit_grants`، `ledger_entries`، `credit_reservations` | `remaining_seconds`، `total_seconds`، `expires_at`؛ دفتر: `kind`، `seconds_delta`، `toman_delta`، `created_at` | اعتبار به **ثانیه** است |
| بستهٔ اعتبار | `packages` | `name`، `minutes`، `price_toman` | |
| درخواست نصب | `installation_requests` | `kind`، `status`، `pbx_type`، `extension_count`، `scheduled_at` | |

### توسعه‌دهنده و انتشار

| موجودیت | جدول/نوع | فیلدهای قابل‌نمایش | یادداشت |
| --- | --- | --- | --- |
| کلید API (API key) | `api_keys` (`kind = integration`) | `label`، `key_prefix`، `scopes[]`، `archive_format`، `expires_at`، `allowed_cidrs[]`، `last_used_at`، `last_used_ip`، `revoked_at` | رمز فقط هنگام ساخت یک‌بار نشان داده می‌شود (`secret`) |
| وب‌هوک (webhook) | `webhooks` | `url`، `events[]`، `active`، `description`، `consecutive_failures`، `disabled_at`، `disabled_reason`، `secret_rotated_at` | رویدادها: `call.complete`، `call.failed`، `balance.low`، `sales.insight` |
| تحویل وب‌هوک | `webhook_deliveries` | `event`، `attempt`، `status_code`، `latency_ms`، `error`، `next_retry_at` | |
| نسخهٔ ماژول (module release) | `module_releases` | `version`، `title`، `severity`، `channel`، `status`، `lab_verified`، `min_freepbx_major`/`max_freepbx_major`، `artifact_size`، `published_at` | سراسری (نه per-tenant) |
| نصب ماژول | `module_installations` | `hostname`، `module_version`، `freepbx_version`، `php_version`، `service_status`، `last_seen_at`، `last_update_status`، `last_error_code` | |
| رویداد به‌روزرسانی ماژول | `module_update_events` | `from_version`، `to_version`، `status`، `message` | `started`/`succeeded`/`failed`/`rolled_back` |
| نسخهٔ جلسه‌نگار (APK) | `jalase_negar_releases` | `version_name`، `version_code`، `min_sdk`، `status`، `rollout_percent`، `channel` | |
| نسخهٔ مدل (model release) | `ml_model_releases` | `kind`، `version`، `channel`، `status`، `size_bytes`، `rollout_percent`، `pinned` | |
| گزارش زمان‌بندی‌شده | `scheduled_reports` + `scheduled_report_runs` | `schedule_mode` (`interval`/`fixed`)، اجرا: `status`، `trigger` | |
| حافظهٔ سازمان | `organization_memories` | `category`، `status`، `version` | |

---

## ۲. enumهای وضعیت: مقدار، برچسب فارسی، نقش نشان (موجود)

### ۲٫۱ وضعیت تماس (`calls.status`، برچسب‌ها از `STATUS_LABELS` در `api.ts`)

| مقدار | برچسب فارسی | تُن در کد | نقش پیشنهادی |
| --- | --- | --- | --- |
| `received` | دریافت‌شده | info | info |
| `reserved` | رزرو اعتبار | violet | info |
| `stored` | ذخیره‌شده | info | info |
| `transcribing` | در حال پیاده‌سازی | info | info |
| `transcribed` | پیاده‌سازی شد | info | info |
| `correcting` | در حال تصحیح متن | violet | info |
| `emotion_queued` | در صف تحلیل لحن | violet | info |
| `emotion_analyzing` | در حال تحلیل لحن | violet | info |
| `analyzing` | در حال تحلیل | warning | warning |
| `analyzed` | تحلیل شد | success | success |
| `billed` | محاسبه شد | success | success |
| `notified` | اطلاع‌رسانی شد | success | success |
| `complete` | کامل | success | success |
| `failed_retryable` | خطای موقت | orange | warning |
| `failed_terminal` | خطای نهایی | danger | danger |
| `canceled` | لغوشده | neutral | neutral |
| `missed` | بی‌پاسخ | danger | danger |

نکته: ستون `status` شامل ۱۷ مقدار بالا (`CALL_STATUSES`) است. در فهرست تماس‌ها، برای تماس‌های غیر `answered` به‌جای `status` همان `call_type` نشان داده می‌شود (`StatusBadge`).

### ۲٫۲ نوع تماس (`calls.call_type`) و جهت (`direction`)

| مقدار | برچسب | تُن | نقش |
| --- | --- | --- | --- |
| `answered` | پاسخ‌داده‌شده | (بدون تُن → neutral؛ در فهرست به‌جای آن `status` نشان داده می‌شود) | neutral |
| `no_answer` | بی‌پاسخ | danger | danger |
| `busy` | مشغول | warning | warning |
| `congestion` | اختلال / اشغال مسیر | orange | warning |
| `failed` | ناموفق | danger | danger |
| `canceled` | لغوشده | neutral | neutral |
| `voicemail` | پیام‌گیر صوتی | neutral | neutral |

| `direction` | برچسب (`CallDetail.tsx`) |
| --- | --- |
| `inbound` | ورودی |
| `outbound` | خروجی |
| `internal` | داخلی |

### ۲٫۳ وضعیت جلسه در سرور (`meetings.status`، `MEETING_STATUS_LABELS`)

| مقدار | برچسب فارسی | تُن در کد | نقش پیشنهادی |
| --- | --- | --- | --- |
| `receiving` | در حال دریافت | info | info |
| `processing` | در حال پردازش | info | info |
| `complete` | کامل | success | success |
| `failed_retryable` | خطای موقت | orange | warning |
| `failed_terminal` | ناموفق | danger | danger |
| `canceled` | لغوشده | neutral | neutral |

وضعیت قطعهٔ جلسه (`meeting_chunks.status`): `received`، `queued`، `transcribing`، `transcribed`، `failed`. نوع ورودی (`input_kind`): `audio`، `text` (جلسهٔ فقط‌متن از اپ). وضعیت محلی اپ (۹ مقدار) در `06-jalase-negar-app.md` بخش ۵ آمده است.

اقدام‌های مجاز بر اساس وضعیت در پنل: «بازتحلیل صورت‌جلسه» فقط `complete`؛ «تلاش مجدد پردازش» در `failed_retryable`، `failed_terminal` (و سرور `processing` را هم می‌پذیرد)؛ ویرایش صورت‌جلسه فقط `complete`؛ حذف برای مالک یا `org_admin`.

### ۲٫۴ کار (`follow_up_tasks`)

| فیلد | مقدار | برچسب | تُن در کد | نقش |
| --- | --- | --- | --- | --- |
| `status` | `open` | باز | neutral | neutral |
| `status` | `in_progress` | در حال انجام | info | info |
| `status` | `done` | انجام شده | success | success |
| `priority` | `high` | بالا | بدون نشان | پیشنهاد: danger |
| `priority` | `normal` | معمولی | بدون نشان | neutral |
| `priority` | `low` | پایین | بدون نشان | neutral |
| `priority` | (خالی) | بدون اولویت | — | — |
| `origin` | `analysis` / `manual` | (برچسب فارسی در UI یافت نشد) ⚠ | — | neutral |
| `kind` رویداد | `created` / `updated` / `note` | (در تاریخچه) | — | neutral |

نماهای فهرست: `overdue` عقب‌افتاده، `today` امروز، `upcoming` آینده، `done` انجام‌شده، `all` همه. مرتب‌سازی: `due_date` موعد، `priority` اولویت، `created_at` زمان ایجاد، `updated_at` آخرین تغییر. «عقب‌افتاده» = موعد گذشته و وضعیت غیر `done` (`is_overdue`).

### ۲٫۵ اشتراک، سفارش، پرداخت

| `subscriptions.status` | برچسب (`SubscriptionPanel`) | نقش پیشنهادی |
| --- | --- | --- |
| `active` | فعال | success |
| `trialing` | آزمایشی | info |
| `pending_payment` | در انتظار پرداخت | warning |
| `expired` | منقضی‌شده (ادمین: «منقضی») | danger |
| `canceled` | لغوشده | neutral |
| `grace` (مشتق در UI؛ در CHECK نیست) | در مهلت تمدید | warning |

| `billing_period` | معنی |
| --- | --- |
| `trial`، `monthly`، `annual`، `legacy` | آزمایشی، ماهانه، سالانه، قدیمی (⚠ برچسب فارسی در UI یافت نشد) |

| `orders.status` | برچسب (`Account.tsx`) | نقش پیشنهادی |
| --- | --- | --- |
| `draft` | پیش‌نویس | neutral |
| `pending_payment` | در انتظار پرداخت | warning |
| `paid` | پرداخت‌شده | success |
| `canceled` | لغوشده | neutral |
| `partially_refunded` | بازپرداخت جزئی | info |
| `refunded` | بازپرداخت‌شده | neutral |

| `orders.kind` | برچسب |
| --- | --- |
| `subscription` | اشتراک |
| `credit` / `credit_purchase` | خرید اعتبار |
| `installation` | نصب و استقرار |
| `operator_addon` | اپراتور اضافه |
| `subscription_upgrade` | ارتقای اشتراک |
| `renewal` | تمدید اشتراک |

| `payment_attempts.status` | برچسب (ادمین `Commerce.tsx`) | نقش پیشنهادی |
| --- | --- | --- |
| `redirected` | هدایت‌شده | info |
| `pending_verification` | نیازمند بررسی | warning |
| `verified` | تأییدشده | success |
| `failed` | ناموفق | danger |
| `canceled` | لغوشده | neutral |
| `expired` | منقضی‌شده | neutral |
| `superseded` | جایگزین‌شده | neutral |

| `refunds.status` | برچسب | نقش |
| --- | --- | --- |
| `pending` | (⚠ برچسب یافت نشد) | warning |
| `completed` | تکمیل‌شده | success |
| `failed` | ناموفق | danger |

| دفتر اعتبار `ledger_entries.kind` | برچسب (`LEDGER_LABELS`) |
| --- | --- |
| `reservation` | رزرو |
| `settlement` | تسویه |
| `release` | آزادسازی |
| `topup` | شارژ |
| `adjustment` | اصلاح |
| `subscription_credit` | هدیه اشتراک |
| `credit_purchase` | خرید اعتبار |
| `expiration` | انقضای اعتبار |
| `refund` | بازپرداخت |

`credit_reservations.status`: `held`، `settled`، `released`. `credit_grants.source`: `monthly_plan`، `credit_purchase`، `prepaid`، `legacy`، `admin_adjustment`، `intro_bonus` (⚠ برچسب فارسی یافت نشد).

`installation_requests.status` (ادمین `Installations.tsx`): `requested` درخواست‌شده، `paid` پرداخت‌شده، `reviewing` در بررسی، `scheduled` زمان‌بندی‌شده، `in_progress` در حال اجرا، `completed` تکمیل‌شده، `canceled` لغوشده.

### ۲٫۶ سازمان، کاربر، کلید، وب‌هوک

| فیلد | مقدار | برچسب | نقش |
| --- | --- | --- | --- |
| `users.role` | `org_admin` | مدیر سازمان | — |
| `users.role` | `operator` | اپراتور | — |
| `users.role` | `viewer` | بیننده | — |
| `tenants.status` | `active` | فعال | success |
| `tenants.status` | `suspended` | معلق (ادمین: هر غیر `active` = «معلق») | danger |
| `tenants.status` | `pending`، `provisioning`، `maintenance_readonly`، `migration_failed`، `deleted` | (⚠ برچسب فارسی جداگانه یافت نشد؛ ادمین فقط فعال/معلق نشان می‌دهد) | pending/provisioning→info؛ maintenance_readonly→warning؛ migration_failed→danger؛ deleted→neutral (پیشنهاد) |
| `api_keys.archive_format` | `wav`، `gzip`، `zip` | قالب آرشیو | — |
| `api_keys.kind` | `integration`، `mobile` | کلید یکپارچه‌سازی / دستگاه موبایل | — |

scopeهای کلید API (`ApiKeyManager.tsx`): `ingest:write` «ارسال تماس و داخلی‌ها»، `module:sync` «به‌روزرسانی و گزارش ماژول مرکز تلفن»، `crm:write` «ثبت نتیجه CRM»، `calls:read` «خواندن تماس‌ها و نتایج تحلیل»، `contacts:read` «جست‌وجوی مخاطب با شماره». scopeهای ویژه که از پنل ساخته نمی‌شوند: `meetings:write` (توکن موبایل)، `ml:publish`.

رویدادهای وب‌هوک (`EVENT_LABELS`): `call.complete` تماس تکمیل‌شده، `call.failed` تماس ناموفق، `balance.low` اعتبار رو به پایان، `sales.insight` بینش فروش.

### ۲٫۷ انتشار و ماژول (پنل ادمین)

| فیلد | مقدار | برچسب | نقش |
| --- | --- | --- | --- |
| `module_releases.status` و `jalase_negar_releases.status` | `draft` | پیش‌نویس | neutral |
| | `published` | منتشرشده | success |
| | `revoked` | لغوشده | danger |
| `ml_model_releases.status` | `uploading` | در حال آپلود | warning |
| | `ready` | آماده | success |
| | `revoked` | باطل‌شده | danger |
| | `deleted` | فایل حذف‌شده | neutral |
| `ml_model_releases.channel` | `latest` / `champion` | آخرین (latest) / برگزیده (champion) | — |
| `module_releases.severity` | `normal`، `recommended`، `critical`، `security` | (⚠ برچسب فارسی در UI بررسی نشد؛ `critical` و `security` بنر هشدار می‌دهند) | normal→neutral، recommended→info، critical→warning، security→danger (پیشنهاد) |
| `module_releases.channel` | `stable`، `beta` | — | — |
| `module_update_events.status` | `started`، `succeeded`، `failed`، `rolled_back` | (⚠ برچسب یافت نشد) | info، success، danger، warning |
| `tenant_database_registry.status` | `provisioning`، `ready`، `maintenance`، `quarantined`، `failed` | (فقط ادمین) | info، success، warning، danger، danger |
| `tenant_backups.status` | `running`، `succeeded`، `failed`، `expired` | — | info، success، danger، neutral |
| `scheduled_report_runs.status` | `queued`، `running`، `succeeded`، `failed` | — | neutral، info، success، danger |

### ۲٫۸ رویداد پردازش (`processing_events.level`)

`info`، `success`، `warning`، `error` (`ProcessingTimeline`): نقش‌های مستقیم info/success/warning/danger. `kind`: `pipeline`، `asr`، `emotion`، `correction`، `llm`، `notify`. `jobs.kind`: `asr`، `emotion`، `correction`، `llm`، `notify`.

---

## ۳. احساس، قصد، نتیجه، روند، اولویت (موجود)

| دامنه | مقدار | برچسب فارسی | تُن در کد | نقش |
| --- | --- | --- | --- | --- |
| احساس (`sentiment`) | `angry` | عصبانی (😡) | danger | danger |
| | `sad` | ناراحت (😢) | orange | warning |
| | `neutral` | خنثی (😐) | neutral | neutral |
| | `satisfied` | راضی (🙂) | info | info |
| | `happy` | خوشحال (😄) | success | success |
| روند احساس (`sentiment_trajectory`) | `improved` | بهبود (↑) | success | success |
| | `worsened` | افت (↓) | danger | danger |
| | `stable` | ثابت (→) | neutral | neutral |
| قصد (`intent`) | `technical_support` | پشتیبانی فنی | — | neutral |
| | `sales_inquiry` | استعلام فروش | — | neutral |
| | `complaint` | شکایت | — | neutral |
| | `consultation` | مشاوره | — | neutral |
| | `billing` | امور مالی | — | neutral |
| | `other` | سایر | — | neutral |
| نتیجهٔ فروش (`outcome`) | `won` | فروش موفق | success | success |
| | `lost` | فروش ناموفق | danger | danger |
| | `follow_up` | نیازمند پیگیری | warning | warning |
| | `interested` | علاقه‌مند | info | info |
| | `not_qualified` | فاقد شرایط | orange | warning |
| | `unknown` | نامشخص | neutral | neutral |
| قطعیت (`certainty`) | `explicit`، `probable`، `unknown` | (⚠ برچسب فارسی یافت نشد) | — | success، info، neutral (پیشنهاد) |
| مرحلهٔ قیف (`funnel_stage`) | `all_calls` کل تماس‌ها، `effective` تماس مؤثر، `opportunities` فرصت فروش*، `qualified` واجد شرایط، `interested` علاقه‌مند، `follow_up` پیگیری، `proposal` پیشنهاد، `won` فروش | از `FunnelStrip.tsx` | — | — |

\* `opportunities` در برچسب‌های UI هست ولی در قید CHECK ستون `funnel_stage` نیست؛ `lost` و `unknown` هم در CHECK هستند ولی برچسب قیف ندارند (⚠ نیازمند تأیید: ممکن است `opportunities` مرحلهٔ محاسبه‌شده باشد).

مقادیر دیگر: سازمان‌دهی حافظه (`organization_memories.category`): `organization_profile`، `products_services`، `terminology`، `policies`، `analysis_rules`، `freeform`؛ `status`: `draft`، `active`، `rejected`، `superseded`، `archived`. حالت گفت‌وگوی دستیار: `normal`، `training`. اسکوپ دستور هوش مصنوعی سازمان: `coach`، `meeting`.

---

## ۴. کدهای خطای API کاربرمحور و پیام فارسی (موجود)

قالب پاسخ خطا: `{"error": {"code", "message", "retryable", "request_id"}}` (به‌علاوهٔ فیلدهای تکمیلی مثل `missing_seqs`). کد وضعیت HTTP از `ERROR_STATUS` می‌آید؛ کدهای «قابل تکرار» (`RETRYABLE_CODES`): `insufficient_credit`، `quota_exceeded`، `subscription_inactive`، `rate_limited`، `internal`، `payment_gateway_unavailable`، `meeting_asr_failed`، `meeting_minutes_failed`، `meeting_audio_storage_unavailable`، `document_pdf_unavailable`، `release_file_unavailable`، `apk_inspection_unavailable`، `speaker_storage_unavailable`.

قاعدهٔ نمایش در کلاینت وب: اگر کد در نگاشت فارسی باشد همان نمایش داده می‌شود؛ وگرنه اگر `message` سرور فارسی باشد همان؛ وگرنه پیام پیش‌فرض (`billingErrorMessage`).

### الف) نگاشت فارسی صریح در `billingErrors.mjs`

| کد | HTTP | پیام فارسی (دقیق) |
| --- | --- | --- |
| `subscription_exists` | ۴۰۹ | اشتراک فعال دارید؛ برای تغییر پلن از بخش «تغییر پلن» در حساب استفاده کنید. |
| `change_conflict` | ۴۰۹ | این تغییر الان قابل انجام نیست؛ وضعیت اشتراک را در حساب بررسی کنید. |
| `plan_not_sellable` | ۴۲۲ | این پلن برای خرید در دسترس نیست؛ پلن دیگری انتخاب کنید. |
| `plan_in_use` | ۴۰۹ | این پلن در حال استفاده است؛ بعد از تغییر مشترکان دوباره تلاش کنید. |
| `order_amount_too_large` | ۴۲۲ | مبلغ سفارش از سقف مجاز بیشتر است؛ مقدار را کمتر کنید یا با پشتیبانی تماس بگیرید. |
| `conflict_idempotency` | ۴۰۹ | این درخواست قبلاً با اطلاعات دیگری ثبت شده است؛ صفحه را تازه کنید و دوباره تلاش کنید. |
| `subscription_inactive` | ۴۰۲ | اشتراک شما فعال نیست؛ از بخش حساب اشتراک را تمدید کنید. |
| `insufficient_credit` | ۴۰۲ | اعتبار کافی نیست؛ از بخش حساب اعتبار شارژ کنید. |
| `quota_exceeded` | ۴۰۲ | سقف مصرف پلن تمام شده است؛ اعتبار شارژ کنید یا پلن را ارتقا دهید. |
| `payment_gateway_unavailable` | ۵۰۲ | درگاه پرداخت پاسخ نمی‌دهد؛ چند دقیقه بعد یا با درگاه دیگری تلاش کنید. |
| `payment_method_unavailable` | ۴۰۹ | این روش پرداخت در دسترس نیست؛ روش دیگری انتخاب کنید. |
| `not_found` | ۴۰۴ | مورد درخواستی پیدا نشد؛ صفحه را تازه کنید. |
| `rate_limited` | ۴۲۹ | تعداد درخواست‌ها زیاد است؛ کمی صبر کنید و دوباره تلاش کنید. |

(`plan_code_exists` در `ERROR_STATUS` هست ولی در این نگاشت نیست؛ ⚠ نیازمند تأیید.)

### ب) کارها (`taskErrors.ts`)

| کد | پیام فارسی |
| --- | --- |
| `task_version_conflict` | این کار تغییر کرده است؛ نسخه تازه را دریافت و تغییرات خود را دوباره ثبت کنید. |
| `task_assignee_invalid` | مسئول انتخاب‌شده دسترسی جاری به تماس ندارد؛ نسخه تازه را دریافت و فرد دیگری انتخاب کنید. |
| `not_found` / `forbidden` | به این کار یا تماس دسترسی ندارید؛ به فهرست برگردید و مورد مجاز دیگری انتخاب کنید. |
| `invalid_request` | اطلاعات معتبر نیست؛ عنوان، موعد و تماس انتخاب‌شده را بررسی و دوباره تلاش کنید. |
| پیش‌فرض | عملیات انجام نشد؛ اتصال و دسترسی را بررسی و دوباره تلاش کنید. |

### ج) کاربران (`EditOrganizationUser.tsx`)

| کد | پیام فارسی |
| --- | --- |
| `conflict_idempotency` | این موبایل یا داخلی به کاربر دیگری اختصاص دارد. شماره دیگری وارد کنید. |
| `invalid_request` | شماره موبایل یا داخلی معتبر وارد کنید. |
| `quota_exceeded` | ظرفیت اپراتورهای پلن تکمیل است؛ از بخش اشتراک ظرفیت را افزایش دهید. |
| `primary_admin_protected` | مدیر اصلی سازمان محافظت شده است؛ برای تغییر نقش یا دسترسی، کاربر دیگری را انتخاب کنید. |
| `panel_access_denied` | فقط دسترسی‌هایی را می‌توانید واگذار کنید که خودتان دارید؛ از مدیر سازمان بخواهید بررسی کند. |
| `forbidden` | اجازهٔ ویرایش کاربران را ندارید؛ از مدیر سازمان بخواهید اقدام کند. |
| پیش‌فرض | ذخیرهٔ اطلاعات ممکن نشد. دوباره تلاش کنید. |

### د) پیام‌های فارسی که خود سرور می‌فرستد (نمونه‌ها)

| کد | HTTP | پیام سرور |
| --- | --- | --- |
| `meeting_not_found` | ۴۰۴ | جلسه پیدا نشد؛ فهرست جلسه‌ها را تازه کنید |
| `meeting_closed` | ۴۰۹ | بازتحلیل فقط برای جلسه‌ی کامل‌شده ممکن است؛ منتظر پایان پردازش بمانید / این جلسه بسته شده است؛ جلسه‌ی جدید شروع کنید |
| `document_not_ready` | ۴۰۹ | منتظر پایان پردازش جلسه بمانید و دوباره تلاش کنید. / صورت‌جلسه هنوز آماده نیست؛ وضعیت پردازش جلسه را بررسی کنید. |
| `document_edit_conflict` | ۴۰۹ | صورت‌جلسه تغییر کرده است؛ متن خود را کپی کنید و صفحه را تازه کنید. |
| `document_pdf_unavailable` | ۵۰۳ | (متن فارسی در سرور؛ راهنمای مستند: «دوباره تلاش کنید یا دکمهٔ چاپ را بزنید») |
| `forbidden` (جلسه‌ها) | ۴۰۳ | فقط مدیر سازمان می‌تواند جلسه‌های دیگران را فیلتر کند |
| `jalase_negar_release_not_found` | ۴۰۴ | UI: هنوز نسخه‌ای از جلسه‌نگار منتشر نشده است. بعداً دوباره بررسی کنید. |
| `export_expired` | ۴۱۰ | UI: پیام «منقضی» در `AssistantExportFiles` |
| `meeting_pairing_invalid` | ۴۰۰ | اپ: «کد جفت‌سازی نامعتبر یا منقضی است؛ در پنل کد جدید بسازید.» |
| `meeting_token_limit` | ۴۰۹ | اپ: «سقف دستگاه‌های متصل پر است؛ در پنل یکی از دستگاه‌ها را ابطال کنید.» |
| `speaker_*` (۶ کد) | ۴۰۴/۴۰۹/۴۲۲/۵۰۳ | پیام‌های اپ در `06-jalase-negar-app.md` بخش ۱۵ |

### ه) شکاف‌ها (⚠ نیازمند تأیید)

| موضوع | مشاهده |
| --- | --- |
| پیام انگلیسی سرور | `unauthorized` («missing bearer token»، «invalid or expired token»)، `tenant_suspended` («tenant is <status>»)، خطای `invalid_request` از اعتبارسنجی («<field>: <msg>»)، `internal` («internal server error»)، و برخی پیام‌های ادمین/وب‌هوک انگلیسی‌اند. اگر مستقیم به کاربر برسند، قاعدهٔ «پیام فارسی با اقدام» نقض می‌شود؛ باید با نگاشت سمت کلاینت پوشانده شوند. |
| کدهای بدون نگاشت فارسی در کلاینت | نمونه: `tenant_suspended`، `api_key_scope_denied`، `api_key_expired`، `ip_not_allowed`، `unsupported_audio`، `asr_no_speech`، `call_retranscription_busy`، `coach_unavailable`، `export_too_large`، `meeting_asr_failed`، `meeting_diarization_failed`، `meeting_minutes_failed`، `worker_timeout`، `internal` |
| `asr_no_speech` | پنل فقط «کد خطا: …» + لینک `/help/errors/asr_no_speech` نشان می‌دهد |

مراجع کدها: هر کد API یک ردیف `help_error_codes` (`source = api`) و مقالهٔ فارسی `error-<code>` دارد؛ لینک عمومی `https://<host>/help/errors/<CODE>`.

---

## ۵. خانوادهٔ کدهای `SS-*` و `JN-*` (موجود)

### `SS-<AREA>-NNNN` — ماژول FreePBX

قالب `SS-<AREA>-NNNN`. منبع: `module_error_codes.json` (۸۸ کد؛ هر ورودی: `code`، `severity`، `retryable`، `title`، `action`، و متن انگلیسی). کدها هرگز دوباره استفاده یا شمارهٔ‌ جدید نمی‌گیرند. پیوند مقاله: `https://<host>/help/errors/<CODE>?v=<نسخهٔ ماژول>`.

| پیشوند | حوزه | تعداد در کاتالوگ | نمونه |
| --- | --- | --- | --- |
| `SS-CFG` | پیکربندی | ۴ | `SS-CFG-1001` پروندهٔ پیکربندی پیدا نشد |
| `SS-SVC` | سرویس | ۵ | `SS-SVC-1001` سرویس به‌دلیل خطای پیکربندی شروع نمی‌شود |
| `SS-HOOK` | هوک ضبط | ۷ | `SS-HOOK-1010` چیدمان ضبط Issabel ناسازگار است |
| `SS-AUD` | فایل صوتی | ۵ | `SS-AUD-1002` فایل صوتی WAV معتبر/کامل نیست |
| `SS-STG` | مرحله‌بندی ضبط | ۸ | `SS-STG-1001` ضبط مرحله‌بندی نشد (کپی یا gzip) |
| `SS-UPL` | ارسال | ۱۹ | `SS-UPL-1001` فراداده‌ٔ لازم تماس موجود نیست |
| `SS-QUE` | صف تلاش مجدد | ۶ | `SS-QUE-1002` صف تلاش مجدد نوشته نشد |
| `SS-SWP` | جاروب یتیم‌ها | ۲ | `SS-SWP-1002` ضبط یتیم بازیابی و صف شد |
| `SS-VMX` | پیام‌گیر | ۳ | `SS-VMX-1001` اسپول پیام‌گیر موجود/خواندنی نیست |
| `SS-MCP` | تماس بی‌پاسخ | ۳ | `SS-MCP-1002` ارسال تماس بی‌پاسخ ناموفق |
| `SS-CDR` | CDR | ۳ | `SS-CDR-1002` جدول CDR ستون‌های لازم را ندارد |
| `SS-EXT` | داخلی‌ها | ۳ | `SS-EXT-1002` FreePBX داخلی برای همگام‌سازی ندارد |
| `SS-SYS` | سیستم | ۱۰ | `SS-SYS-1010` پروفایل Issabel پشتیبانی نمی‌شود |
| `SS-UPD` | به‌روزرسانی | ۷ | `SS-UPD-1001` به‌روزرسانی خودکار روی این میزبان ممکن نیست |
| `SS-DEP` | وابستگی | ۳ | `SS-DEP-1002` افزونهٔ PHP لازم نصب نیست |

شدت (`severity`) در کاتالوگ: `error`، `warning`، `info` (نقش‌ها: danger، warning، info). `retryable` بولی.

### `JN-<AREA>-NNNN` — اپ جلسه‌نگار

قالب `JN-<AREA>-NNNN`. فهرست ماشین‌خوان مرکزی پیدا نشد (⚠ نیازمند تأیید)؛ مرجع، کد اپ و README است. حوزه‌ها: `ASR`، `INTRO`، `MDL`، `MTG`، `PERM`، `REC`، `SPK`، `TOUR`.

| کد | حوزه | آیا به کاربر نشان داده می‌شود؟ |
| --- | --- | --- |
| `JN-ASR-0001`، `JN-ASR-0002` | رونویسی زنده | بله |
| `JN-MDL-0001` | دانلود مدل | بله |
| `JN-MTG-0001` | فهرست جلسه‌ها | بله |
| `JN-REC-0003`، `JN-REC-0004` | ضبط | بله |
| `JN-SPK-0001` | همگام‌سازی افراد | بله |
| `JN-TOUR-0001` | تور | بله |
| `JN-INTRO-0001`، `JN-PERM-0001`، `JN-PERM-0002`، `JN-REC-0001`، `JN-REC-0002`، `JN-REC-0005` | — | خیر (log) |

معنی و پیام هر کد در `06-jalase-negar-app.md` بخش ۱۶.

### سه قالب کد در یک نگاه

| نوع | قالب | نمونه | کاربر |
| --- | --- | --- | --- |
| API | snake_case | `insufficient_credit` | پنل وب، اپ، یکپارچه‌سازی‌ها |
| ماژول | `SS-AREA-NNNN` | `SS-UPL-1001` | مدیر مرکز تلفن |
| اپ | `JN-AREA-NNNN` | `JN-REC-0003` | کاربر اپ |

---

## ۶. الگوهای حالت: بارگذاری، خالی، خطا، بی‌دسترسی، در حال پردازش، آفلاین (موجود)

### ۶٫۱ مؤلفه‌های مشترک وب

| مؤلفه | فایل | کار | حالت |
| --- | --- | --- | --- |
| `Skeleton` / `SkeletonRegion` | `shared/components/Skeleton.tsx` | مستطیل نگهدارنده (`aria-hidden`)؛ ناحیه یک‌بار «در حال بارگذاری» را اعلام می‌کند (`role=status`) | بارگذاری |
| `SkeletonTable` | همان | جدول با سرستون واقعی و ردیف‌های اسکلتی؛ انواع سلول `text`، `badge`، `badges`، `button` | بارگذاری فهرست |
| `SkeletonStatCard`، `SkeletonChartCard`، `SkeletonBreakdown`، `SkeletonForm`، `SkeletonCards`، `SkeletonPanel` | همان | اسکلت کارت آمار، نمودار، تفکیک، فرم، کارت‌ها، پنل | بارگذاری |
| `Loading` | `Widgets.tsx` | جایگزین عمومی (= `SkeletonPanel`)؛ لوگوی برند فقط برای اولین بار | بارگذاری |
| `BrandLoader`، `RouteLoadingOverlay` | `BrandLoader.tsx` | لوگوی متحرک؛ فقط بارگذاری اول/تغییر مسیر | بارگذاری اولیه |
| `ProcessingIndicator` | `ProcessingIndicator.tsx` | نشانگر «در حال پردازش…» (چهار مربع) | در حال پردازش |
| `ProcessingCard` | `Widgets.tsx` | مراحل پردازش (تماس: `PIPELINE_STEPS`؛ جلسه: «دریافت صدا»، «تبدیل گفتار»، «تفکیک گوینده»، «صورت‌جلسه») + درصد + `progress_detail` | در حال پردازش |
| `ProcessingTimeline` | `ProcessingTimeline.tsx` | رویدادهای `processing_events` با سطح | در حال پردازش/خطا |
| `Empty` | `Widgets.tsx` | «موردی یافت نشد.» (قابل جایگزینی) + زیرمتن «با ثبت داده‌های بیشتر، جزئیات این بخش نمایش داده می‌شود.» + تصویر | خالی |
| `PanelEmpty` | `PanelEmpty.tsx` | تصویر، عنوان پررنگ، توضیح یک‌خطی، کنش اختیاری | خالی |
| `ErrorBox` | `Widgets.tsx` | کادر قرمز `role=alert`؛ پیام خطا بالای صفحه/فرم | خطا |
| `Toast` | `Toast.tsx` | پیام بالا-وسط، ۶ ثانیه، دکمه «بستن پیام» (`aria-label`)؛ `role=alert` | بازخورد گذرا |
| `ConfirmDialog` | `ConfirmDialog.tsx` | `title`، `description`، `confirmLabel`، `cancelLabel` (پیش‌فرض «انصراف»)، `destructive`، `busy` | تأیید عملیات مخرب |
| `FormDialog` | `FormDialog.tsx` | فرم در دیالوگ با `submitLabel`، `busy`، `error` | ویرایش |
| `OverflowMenu` | `OverflowMenu.tsx` | منوی «عملیات بیشتر» با موارد `disabled` | اقدام ثانویه |
| `PaginatedTable` + `Pagination` | `shared/components/PaginatedTable.tsx`، `Widgets.tsx` | جدول صفحه‌بندی‌شده با `size`/`offset`، انتخاب اندازهٔ صفحه (`PageSizeSelect`) | فهرست |
| `FilterBar` / `FilterSelect` | `shared/components/FilterBar.tsx` | نوار فیلتر با چیپ‌های فعال، `allLabel` پیش‌فرض «همه» | فیلتر |
| `JaliliDatePicker` (`JalaliDatePicker`) | `shared/components/JalaliDatePicker.tsx` | انتخاب تاریخ جلالی؛ placeholder «انتخاب تاریخ» | فرم |
| `ToggleSwitch` | `shared/components/ToggleSwitch.tsx` | سوییچ | فرم |
| `useResource` | `shared/lib/useResource.ts` | وضعیت‌ها `initial`، `refreshing`، `ready`، `error`؛ بازخوانی بی‌صدا (`reload({silent:true})`) | داده‌خوانی |

الگوی بارگذاری معمول صفحه‌های پنل: `initial` → اسکلت هم‌شکل جدول؛ `refreshing` → داده قبلی می‌ماند (نظرسنجی هر ۳ ثانیه برای جلسه‌های فعال و هر `POLL_INTERVAL_MS` در فهرست)؛ `error` → `ErrorBox` + دکمهٔ تلاش/بازگشت؛ `ready` بدون داده → `Empty`/`PanelEmpty`.

### ۶٫۲ مؤلفه‌های اپ جلسه‌نگار

| مؤلفه | کار |
| --- | --- |
| `SsEmptyState` | تصویر + عنوان + راهنما + کنش |
| `SsProcessingMark` | چهار مربع تپنده + یک خط متن؛ بدون نوار پیشرفت |
| `SsToastHost` | پیام زیر نوار بالا؛ کنش اختیاری («بازگردانی»)؛ صف |
| `SsBadge` | نشان مربعی (رنگ ۱۰٪ + حاشیه ۵۰٪) |
| `SsCard` / `SsSectionTitle` | کارت با نوار عنوان |
| `AlertDialog` / `showModalBottomSheet` | تأیید و انتخاب |
| `_SkeletonList` | اسکلت فهرست جلسه‌ها (داخلی) |
| `CircularProgressIndicator` | بارگذاری ساده (جزئیات جلسه، مدل‌ها، افراد) |

### ۶٫۳ کاتالوگ الگو به تفکیک حالت

| حالت | وب (پنل) | اپ | قاعدهٔ محتوا |
| --- | --- | --- | --- |
| بارگذاری | `Skeleton*`/`Loading`؛ اولین بار `BrandLoader` | `_SkeletonList`، `CircularProgressIndicator`، `SsProcessingMark` | هم‌شکل با محتوای نهایی؛ سرستون‌ها اسکلتی نمی‌شوند؛ برچسب دسترسی «در حال بارگذاری» |
| خالی (هیچ داده) | `Empty`/`PanelEmpty` | `SsEmptyState` | عنوان + اقدام بعدی («برای ضبط جلسه، اپ جلسه‌نگار را متصل کنید» / «ضبط اولین جلسه») |
| خالی (فیلتر/جست‌وجو) | `Empty` با راهنمای تغییر فیلتر | `SsEmptyState` «جلسه‌ای پیدا نشد» + «پاک کردن فیلترها» | کنش پاک‌کردن فیلتر |
| خطای بارگذاری | `ErrorBox` + دکمهٔ بازگشت/تلاش | `SsEmptyState` + «تلاش مجدد» (+ کد `JN-*`) | متن + اقدام + (در صورت وجود) کد |
| خطای عملیات | `ErrorBox` یا خطای درون‌دیالوگ (`FormDialog.error`) + `Toast` | `SsToastHost.show` | پیام اقدام‌دار فارسی |
| بی‌دسترسی (permission-denied) | کدهای `forbidden`، `panel_access_denied`، `api_key_scope_denied`؛ منوی کنش‌ها با `disabled`؛ نقش `viewer` فقط خواندنی | مجوز میکروفون/دوربین/اعلان: متن با مسیر «تنظیمات گوشی» | نام مجوز + مسیر فعال‌سازی |
| در حال پردازش | `ProcessingCard`/`ProcessingTimeline`/`ProcessingIndicator` + نظرسنجی | `SsProcessingMark` + خط وضعیت (+ درصد برای گوینده) | مرحله فعلی + «پس از پایان…» |
| نیازمند بازخوانی/تعارض | `document_edit_conflict`، `task_version_conflict` با دستور «صفحه را تازه کنید» | `textSyncPending` + «ارسال دوباره» | کنش بازیابی |
| آفلاین | ⚠ نیازمند تأیید: الگوی ویژهٔ آفلاین در پنل یافت نشد؛ `request` در خطای شبکه استثنای مرورگر می‌اندازد | فهرست و ویرایش محلی کار می‌کند؛ ارسال به تعویق می‌افتد؛ پیام «ارتباط با سرور برقرار نشد؛ اینترنت و آدرس سرور را بررسی کنید.»؛ ندارد «نوار آفلاین» | محلی‌بودن + اقدام |
| موفقیت | `Toast`؛ اعلان سبز درون‌صفحه (`role=status`) مثل «عنوان جلسه ذخیره شد.»، «صورت‌جلسه ذخیره شد.» | `SsToastHost` | کوتاه، بدون اقدام |
| عملیات مخرب | `ConfirmDialog destructive`: «حذف جلسه» — «این جلسه، فایل صوتی، متن، گوینده‌ها و صورت‌جلسه برای همیشه حذف می‌شوند. این عملیات قابل بازگشت نیست.» | دیالوگ + «بازگردانی» ۵ ثانیه‌ای پس از سوایپ | بازگشت‌ناپذیری را صریح بگو |

### ۶٫۴ قاعدهٔ پیام (AGENTS.md قاعدهٔ ۱۰)

> هر پیام خطا یک اقدام بعدی را نام می‌برد. هیچ بن‌بستی نیست.

قواعد کامل (`skills/sedasanj-error-codes/SKILL.md`): پیام قابل‌اقدام باشد (چه چیز را بررسی/اجرا کنید)؛ بدون راز (کلید API، رمز آرشیو، شماره تلفن) و بدون `repr(exc)` یا بازتاب ورودی کاربر؛ کدها هرگز دوباره استفاده یا بازشماره نمی‌شوند؛ زبان رابط و مستند فارسی، شناسه‌ها/کدها/پیام‌های لاگ/کامنت‌ها انگلیسی؛ کد و دستور داخل متن فارسی LTR با رقم لاتین. ساختار پیشنهادی پیام (نمونه‌های موجود همین الگو را دارند): «<چه شد>؛ <چه کنید>» با نقطه‌ویرگول فارسی — مثال: «اعتبار کافی نیست؛ از بخش حساب اعتبار شارژ کنید.».

الگوهای واژگان اقدام که در پیام‌های موجود تکرار می‌شوند (برای یکدستی در بازطراحی): «دوباره تلاش کنید»، «صفحه را تازه کنید»، «از بخش … … را بزنید/بررسی کنید»، «در پنل … بسازید/شارژ کنید»، «از مدیر سازمان بخواهید»، «برنامه را ببندید و دوباره باز کنید»، «با پشتیبانی تماس بگیرید».

---

## ۷. قراردادهای نمایش داده (موجود)

| موضوع | قرارداد |
| --- | --- |
| تاریخ | جلالی؛ وب `toLocaleDateString("fa-IR-u-ca-persian")` و `JalaliDatePicker`؛ اپ `formatJalaliDay` («۱۵ آبان ۱۴۰۵»)؛ API تاریخ را میلادی/ISO می‌دهد (`due_date` نوع `date`) |
| منطقهٔ زمانی | `Asia/Tehran` پیش‌فرض سازمان؛ «امروز» برای کارها از منطقهٔ سازمان محاسبه می‌شود |
| ارقام | فارسی در متن؛ لاتین برای کد، شماره تلفن (با `data-keep-latin-digits`)، URL، نسخه |
| مدت | `mm:ss` یا `h:mm:ss`؛ وب `fmt.duration`؛ LTR |
| درصد | وب `fmt.percent` → «<n>٪» |
| پول | تومان (`*_toman`)؛ درگاه ریال (`amount_rial`) |
| اعتبار | ثانیه در دفتر (`seconds_delta`)، «دقیقه» در بسته‌ها (`minutes`) |
| نقش‌ها | `org_admin` مدیر سازمان، `operator` اپراتور، `viewer` بیننده؛ مدیریت جلسه: `CAN_MANAGE_MEETINGS = org_admin, operator` |
| دیدن جلسه | مالک + `org_admin` (`apply_meeting_scope`) |

---

## ۸. سؤال‌های باز

| # | سؤال | چرا مهم است |
| --- | --- | --- |
| ۱ | برچسب فارسی برای `tenants.status` (غیر از فعال/معلق)، `billing_period`، `credit_grants.source`، `module_releases.severity`، `module_update_events.status`، `follow_up_tasks.origin`، `sales_insights.certainty`، `refunds.status = pending` تعریف نشده؛ متن رسمی چیست؟ | نمایش یکدست در ادمین/پنل |
| ۲ | تُن‌های `violet` و `orange` خارج از پنج نقش‌اند؛ آیا در بازطراحی به نقش‌های موجود فرو می‌ریزند (پیشنهاد این سند) یا دو نقش تازه می‌گیرند؟ | سیستم رنگ |
| ۳ | `funnel_stage` در پایگاه‌داده `opportunities` ندارد ولی `FunnelStrip` دارد؛ و `lost`/`unknown` برچسب قیف ندارند. منبع حقیقت کدام است؟ | درستی نمودار قیف |
| ۴ | پیام‌های انگلیسی سرور (`unauthorized`، `tenant_suspended`، خطای اعتبارسنجی `invalid_request`، `internal`) را کجا فارسی کنیم: سرور یا نگاشت کلاینت؟ | قاعدهٔ «پیام فارسی با اقدام» |
| ۵ | الگوی آفلاین در پنل وب (نوار «اتصال قطع است» و بازخوانی خودکار) تعریف شود؟ اپ هم نشانگر آفلاین صریح بگیرد؟ | تجربهٔ خطای شبکه |
| ۶ | `meetings` به‌عنوان موجودیت دارای کار (task) و صورت‌جلسهٔ ساختاریافته با موعد/مسئول: مدل داده نهایی؟ (جزئیات در `06-jalase-negar-app.md` بخش ۲۱) | صفحهٔ «کارها» |
| ۷ | وضعیت `grace` در `SubscriptionPanel` در CHECK مدل `subscriptions.status` نیست؛ از کجا می‌آید (مشتق سمت سرور؟) | دقت نشان وضعیت اشتراک |
| ۸ | فهرست کامل `operator_call_scores.status` و `analysis_runs.status` در قید CHECK نیست؛ مقدارهای واقعی؟ | نشان وضعیت امتیاز/تحلیل |
| ۹ | آیا برای `JN-*` فهرست ماشین‌خوان و مقالهٔ راهنما در `help_error_codes` ایجاد می‌شود (مثل `SS-*`)؟ | دسترسی به راهنمای خطا از اپ |
| ۱۰ | `MeetingListItem` در TypeScript پنل `summary`، `owner_id`، `processing` دارد ولی API فهرست `owner_user_id` می‌دهد و `summary`/`processing` ندارد؛ و جست‌وجو `q` فقط روی `title` است | ستون «خلاصه» و جست‌وجوی «عنوان، متن و صورت‌جلسه» در فهرست جلسه‌ها |
| ۱۱ | `plan_code_exists` در `ERROR_STATUS` هست ولی نگاشت فارسی ندارد | پیام ایجاد پلن در ادمین |
