"""Document stand-alone Jalase-Negar sign-up and the admin users page (help center)."""

# ruff: noqa: E501 - Persian help prose is kept in complete paragraphs.

import sqlalchemy as sa

from alembic import op

revision = "0146_jalase_signup_help"
down_revision = "0145_product_and_signup_channel"
branch_labels = None
depends_on = None

ARTICLES = (
    (
        "jalase-negar-standalone-signup",
        "ثبت‌نام مستقل جلسه‌نگار با شماره موبایل",
        "فعال‌سازی ورود سریع جلسه‌نگار و عیب‌یابی خطای jalase_signup_disabled.",
        "<h2>نشانه‌ها</h2><p>اپ جلسه‌نگار هنگام ورود با موبایل پیام «ثبت‌نام مستقل هنوز فعال نشده» می‌دهد و خطای "
        '<code dir="ltr">jalase_signup_disabled</code> برمی‌گردد.</p>'
        "<h2>علت</h2><p>کلید «ثبت‌نام مستقل جلسه‌نگار با شماره موبایل» در تنظیمات پلتفرم خاموش است. این کلید به‌صورت پیش‌فرض خاموش است.</p>"
        "<h2>رفع مشکل</h2><ol><li>با حساب مدیر کل وارد ادمین شوید.</li>"
        "<li>به تنظیمات، برگهٔ مدل‌ها و بخش «صورت‌جلسهٔ جلسات» بروید.</li>"
        "<li>کلید «ثبت‌نام مستقل جلسه‌نگار با شماره موبایل» را روشن و ذخیره کنید.</li>"
        "<li>مطمئن شوید قالب پیامک کد تأیید در تنظیمات پیامک فعال است.</li></ol>"
        "<h2>تأیید رفع مشکل</h2><p>در اپ شماره‌ای را وارد کنید؛ کد پیامک می‌شود. پس از ورود، کاربر در صفحهٔ کاربران ادمین با فیلتر محصول «جلسه‌نگار» دیده می‌شود.</p>"
        "<h2>پیشگیری</h2><p>پیش از انتشار اپ، کلید را فقط پس از آزمایش پیامک و پلن رایگان روشن کنید. خاموش کردن کلید ورود کاربران موجود را هم متوقف می‌کند؛ کلیدهای دستگاه فعلی کار می‌کنند.</p>",
        "jalase_signup_disabled",
        "کلید ثبت‌نام مستقل جلسه‌نگار را در تنظیمات ادمین روشن کنید.",
    ),
    (
        "admin-users-bulk-actions",
        "کاربران ادمین: خروجی و عملیات گروهی",
        "فیلتر کاربران جلسه‌نگار، خروجی Excel یا CSV و عملیات گروهی با پیش‌نمایش.",
        "<h2>نشانه‌ها</h2><p>عملیات گروهی یا خروجی با خطای "
        '<code dir="ltr">bulk_action_too_large</code> یا <code dir="ltr">sms_template_missing</code> رد می‌شود.</p>'
        "<h2>علت</h2><p>هر اجرای گروهی حداکثر ۵۰۰ کاربر و هر خروجی حداکثر ۵۰٬۰۰۰ ردیف دارد. پیامک گروهی فقط با قالب فعال «پیام گروهی به کاربران جلسه‌نگار» ارسال می‌شود. عملیات گروهی فقط روی حساب‌های جلسه‌نگار اجرا می‌شود، نه سازمان‌های صداسنج.</p>"
        "<h2>رفع مشکل</h2><ol><li>فیلترها (محصول، کانال، پلن، وضعیت، تاریخ، جست‌وجو) را محدودتر کنید تا تعداد زیر سقف بماند.</li>"
        "<li>برای پیامک، در تنظیمات پیامک قالب «پیام گروهی به کاربران جلسه‌نگار» را با شناسهٔ sms.ir بسازید و فعال کنید. پارامترهای NAME و MESSAGE را در قالب بگذارید.</li>"
        "<li>ابتدا پیش‌نمایش را اجرا کنید تا تعداد دقیق کاربران را ببینید، سپس اجرای نهایی را بزنید.</li></ol>"
        "<h2>تأیید رفع مشکل</h2><p>پس از اجرا، رکورد ممیزی با شناسهٔ اجرا و تعداد انجام‌شده‌ها ثبت می‌شود. شماره‌های موبایل در ممیزی ذخیره نمی‌شوند.</p>"
        "<h2>پیشگیری</h2><p>پیش از تعلیق یا اعطای اعتبار گروهی، خروجی گرفتن از همان فیلتر را بررسی کنید. تعلیق حساب، ورود کاربر را فوراً قطع می‌کند.</p>",
        "bulk_action_too_large",
        "فیلتر را محدودتر کنید تا کمتر از ۵۰۰ کاربر انتخاب شود.",
    ),
)
EXTRA_CODES = (
    (
        "sms_template_missing",
        "admin-users-bulk-actions",
        "قالب پیامک گروهی فعال نیست.",
        "قالب «پیام گروهی به کاربران جلسه‌نگار» را در تنظیمات پیامک فعال کنید.",
    ),
)


def upgrade() -> None:
    bind = op.get_bind()
    for position, (slug, title, summary, body, code, action) in enumerate(ARTICLES, start=152):
        bind.execute(
            sa.text(
                "INSERT INTO help_articles (slug,title,summary,body_html,body_plain,kind,status,"
                "position,published_at) "
                "VALUES (:slug,:title,:summary,:body,:summary,'article','published',:position,now()) "
                "ON CONFLICT (slug) DO NOTHING"
            ),
            {"slug": slug, "title": title, "summary": summary, "body": body, "position": position},
        )
        bind.execute(
            sa.text(
                "INSERT INTO help_error_codes (code,source,severity,article_id,title,quick_action) "
                "SELECT :code,'api','error',id,:summary,:action "
                "FROM help_articles WHERE slug=:slug ON CONFLICT (code) DO NOTHING"
            ),
            {"slug": slug, "code": code, "summary": summary, "action": action},
        )
    for code, slug, summary, action in EXTRA_CODES:
        bind.execute(
            sa.text(
                "INSERT INTO help_error_codes (code,source,severity,article_id,title,quick_action) "
                "SELECT :code,'api','error',id,:summary,:action "
                "FROM help_articles WHERE slug=:slug ON CONFLICT (code) DO NOTHING"
            ),
            {"slug": slug, "code": code, "summary": summary, "action": action},
        )


def downgrade() -> None:
    bind = op.get_bind()
    codes = [row[4] for row in ARTICLES] + [row[0] for row in EXTRA_CODES]
    for code in codes:
        bind.execute(sa.text("DELETE FROM help_error_codes WHERE code=:code"), {"code": code})
    for slug, *_ in ARTICLES:
        bind.execute(sa.text("DELETE FROM help_articles WHERE slug=:slug"), {"slug": slug})
