"""Document separately scoped site and customer scripts."""

import sqlalchemy as sa

from alembic import op

revision = "0144_site_scripts_help"
down_revision = "0143_jalase_negar_desktop_builds"
branch_labels = None
depends_on = None

SLUG = "site-scripts-guide"
TITLE = "مدیریت اسکریپت صفحات عمومی و پنل مشتری"
SUMMARY = "افزودن، حذف و عیب‌یابی کد سرویس‌ها در head و body با دسترسی مدیر کل."
BODY = (
    "<h2>نشانه‌ها</h2><p>اسکریپت اجرا نمی‌شود یا ذخیره با خطای "
    '<code dir="ltr">site_scripts_invalid</code> رد شده است.</p>'
    "<h2>علت</h2><p>تگ ناقص، HTML غیر از script، ویژگی پشتیبانی‌نشده یا نشانی نامعتبر "
    "وارد شده است. اتصال سرویس بیرونی نیز ممکن است در شبکه مسدود باشد.</p>"
    "<h2>رفع مشکل</h2><ol><li>با حساب مدیر کل به تنظیمات، تنظیمات سایت بروید.</li>"
    "<li>کد معتبر سرویس مورد اعتماد را همراه تگ باز و بسته script در یکی از چهار فیلد "
    "صفحات عمومی یا پنل مشتری، داخل head یا انتهای body وارد کنید. هر فیلد حداکثر "
    "۳۰ اسکریپت و ۱۰۰٬۰۰۰ نویسه دارد. src باید HTTPS یا مسیر داخلی باشد.</li>"
    "<li>رمز عبور و در صورت فعال بودن، کد دومرحله‌ای را وارد و ذخیره کنید. "
    "کدها به داده‌های قابل مشاهده مشتری دسترسی دارند؛ رمز و کلید خصوصی قرار ندهید.</li>"
    "<li>صفحه مقصد را دوباره بارگذاری کنید. فیلد خالی، اسکریپت آن محل را حذف می‌کند.</li>"
    "<li>در صورت شکست، Network و Console مرورگر را برای نشانی سرویس و محدودیت CSP "
    "بررسی کنید. سیاست سفارشی CONTENT_SECURITY_POLICY می‌تواند اجرای سرویس را مسدود کند.</li></ol>"
    "<h2>تأیید رفع مشکل</h2><p>یک صفحه عمومی را بدون ورود و پنل را پس از ورود بررسی کنید؛ "
    "هر بخش فقط اسکریپت خودش را اجرا می‌کند. پنل ادمین کدها را اجرا نمی‌کند. "
    "بارگذاری بعد از تشخیص ورود است، نه هنگام تجزیه اولیه HTML؛ document.write مناسب نیست. "
    "کدها در جابه‌جایی صفحات همان بخش دوباره اجرا نمی‌شوند. ورود و خروج صفحه را برای "
    "پاک شدن اثر اسکریپت‌های بخش قبلی دوباره بارگذاری می‌کند.</p>"
    "<h2>پیشگیری</h2><p>ابتدا کد را در محیط آزمایشی بررسی کنید. برای رفع اختلال، کد را "
    "از ادمین حذف و صفحه مقصد را تازه کنید. حذف تگ، اثر کد اجراشده را تا بازآوری برنمی‌گرداند.</p>"
)


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "INSERT INTO help_articles (slug,title,summary,body_html,body_plain,kind,status,"
            "position,published_at) "
            "VALUES (:slug,:title,:summary,:body,:summary,'article','published',151,now()) "
            "ON CONFLICT (slug) DO NOTHING"
        ),
        {"slug": SLUG, "title": TITLE, "summary": SUMMARY, "body": BODY},
    )
    bind.execute(
        sa.text(
            "INSERT INTO help_error_codes (code,source,severity,article_id,title,quick_action) "
            "SELECT 'site_scripts_invalid','api','error',id,:summary,:action "
            "FROM help_articles WHERE slug=:slug ON CONFLICT (code) DO NOTHING"
        ),
        {
            "slug": SLUG,
            "summary": SUMMARY,
            "action": "تگ‌های script و نشانی‌ها را اصلاح و دوباره ذخیره کنید.",
        },
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM help_error_codes WHERE code='site_scripts_invalid'"))
    bind.execute(sa.text("DELETE FROM help_articles WHERE slug=:slug"), {"slug": SLUG})
