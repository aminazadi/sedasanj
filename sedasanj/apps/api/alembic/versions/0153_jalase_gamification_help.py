"""Help for Jalase-Negar levels, badges, gift tokens and friend invites."""

# ruff: noqa: E501 - Persian help prose is kept in complete paragraphs.

import sqlalchemy as sa

from alembic import op

revision = "0153_jalase_gamification_help"
down_revision = "0152_jalase_gamification"
branch_labels = None
depends_on = None

SLUG = "jalase-negar-badges-and-invites"
TITLE = "نشان‌ها، توکن هدیه و دعوت دوستان در جلسه‌نگار"
SUMMARY = "سطح و نشان‌های جلسه‌نگار، سقف ماهانهٔ توکن هدیه، و عیب‌یابی خطاهای دعوت دوستان."
BODY = (
    "<h2>سطح و نشان‌ها</h2><p>با ثبت جلسه و ساختن سند، امتیاز می‌گیرید (هر جلسه ۱۰ و هر سند ۵ امتیاز) و سطح شما بالا می‌رود. هر نشان یک هدف دارد، مثل اولین جلسه یا چهار هفتهٔ پیاپی. رسیدن به نشان، مقداری توکن هدیه می‌دهد که مثل ساعت اضافه مصرف می‌شود و ۶۰ روز اعتبار دارد.</p>"
    "<h2>سقف ماهانهٔ هدیه</h2><p>توکن هدیهٔ نشان‌ها در هر ماه به درصدی از سهمیهٔ پلن شما محدود است. اگر سقف پر شده باشد، نشان را می‌گیرید ولی هدیه‌اش صفر یا کمتر از معمول است؛ هدیه‌ای که ماه بعد گرفته نشود جبران نمی‌شود.</p>"
    "<h2>دعوت دوستان</h2><p>کد دعوت خود را از بخش «پیشرفت من» بردارید و به دوستتان بدهید. دوست شما باید با شمارهٔ موبایل جدید ثبت‌نام کند و ظرف ۷ روز از ساخت حساب، کد را وارد کند. پس از آن هر دو نفر توکن هدیه می‌گیرید. هر کد در ماه حداکثر ۱۰ دعوت پاداش‌دار دارد و هر حساب فقط یک بار می‌تواند کد وارد کند.</p>"
    '<h2>خطاها</h2><p><code dir="ltr">invite_invalid</code>: کد اشتباه است یا کد خودتان را وارد کرده‌اید. <code dir="ltr">invite_not_allowed</code>: حساب شما بیش از یک هفته پیش ساخته شده، قبلاً کد وارد کرده‌اید یا صاحب کد به سقف ماهانه رسیده است. <code dir="ltr">invite_disabled</code>: دعوت دوستان فعلاً خاموش است.</p>'
    "<h2>رفع مشکل</h2><ol><li>کد را دوباره و بدون فاصله وارد کنید؛ حروف بزرگ و کوچک فرقی ندارند.</li>"
    "<li>اگر حساب شما قدیمی است، از دوستتان بخواهید کد شما را وارد کند؛ پاداش دعوت‌کننده به شما می‌رسد.</li>"
    "<li>اگر پیام «غیرفعال» می‌بینید، بعداً دوباره امتحان کنید.</li></ol>"
    "<h2>برای مدیر سیستم</h2><p>نشان‌ها و مقدار هدیهٔ هرکدام در ادمین، صفحهٔ «نشان‌های جلسه‌نگار» ویرایش می‌شوند. سقف ماهانهٔ هدیه (درصد سهمیهٔ پلن) و مقدار توکن دعوت در تنظیمات مدل‌ها هستند؛ سقف صفر هدیهٔ نشان‌ها و توکن دعوت صفر دعوت را خاموش می‌کند. مقدارهای اولیه (۲۰٪ و ۲۰٬۰۰۰ توکن) تخمینی‌اند.</p>"
    "<h2>تأیید رفع مشکل</h2><p>پس از ثبت کد، «ساعت باقی‌مانده» در اپ بیشتر می‌شود و در بخش پیشرفت، تعداد دوستان دعوت‌شده به‌روز می‌شود.</p>"
)
CODES = (
    (
        "invite_invalid",
        "کد دعوت درست نیست.",
        "کد را دوباره و بدون فاصله وارد کنید یا از دوستتان بگیرید.",
    ),
    (
        "invite_not_allowed",
        "این کد دعوت قابل استفاده نیست.",
        "کد دعوت فقط برای حساب‌های تازه (کمتر از یک هفته) و یک‌بار قابل ثبت است.",
    ),
    (
        "invite_disabled",
        "دعوت دوستان فعلاً خاموش است.",
        "بعداً دوباره امتحان کنید؛ مدیر می‌تواند آن را در تنظیمات روشن کند.",
    ),
)


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "INSERT INTO help_articles (slug,title,summary,body_html,body_plain,kind,status,"
            "position,published_at) "
            "VALUES (:slug,:title,:summary,:body,:summary,'article','published',155,now()) "
            "ON CONFLICT (slug) DO NOTHING"
        ),
        {"slug": SLUG, "title": TITLE, "summary": SUMMARY, "body": BODY},
    )
    for code, summary, action in CODES:
        bind.execute(
            sa.text(
                "INSERT INTO help_error_codes (code,source,severity,article_id,title,quick_action) "
                "SELECT :code,'api','error',id,:summary,:action "
                "FROM help_articles WHERE slug=:slug ON CONFLICT (code) DO NOTHING"
            ),
            {"slug": SLUG, "code": code, "summary": summary, "action": action},
        )


def downgrade() -> None:
    bind = op.get_bind()
    for code, _summary, _action in CODES:
        bind.execute(sa.text("DELETE FROM help_error_codes WHERE code=:code"), {"code": code})
    bind.execute(sa.text("DELETE FROM help_articles WHERE slug=:slug"), {"slug": SLUG})
