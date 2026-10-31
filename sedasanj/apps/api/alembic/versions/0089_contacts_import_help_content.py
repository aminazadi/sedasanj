"""Help content for progressive contact CSV import."""

import sqlalchemy as sa

from alembic import op

revision = "0089_contacts_import_help_content"
down_revision = "0088_site_footer_help_content"
branch_labels = None
depends_on = None

ARTICLE_SLUG = "contacts-csv-import-guide"
ARTICLE_TITLE = "ورود مرحله‌ای مخاطبان از CSV"
ARTICLE_SUMMARY = "بارگذاری فایل مخاطبان بدون سقف حجم یا تعداد ردیف، همراه با درصد پیشرفت."
ARTICLE_BODY = (
    "<h2>نشانه‌ها</h2><p>فایل بزرگ است یا ورود مخاطبان متوقف شده است. خطای "
    '<code dir="ltr">invalid_request</code> به معنی نیاز به اصلاح ساختار فایل است.</p>'
    "<h2>علت</h2><p>ردیف عنوان یا اطلاعات مخاطب نامعتبر است؛ قطع شبکه نیز ارسال بخش بعدی "
    "را متوقف می‌کند. محدودیت تعداد درخواست‌ها باعث مکث خودکار و سپس ادامه می‌شود.</p>"
    "<h2>رفع مشکل</h2><ol><li>از دفترچه تلفن، ایمپورت CSV را باز کنید و فایل نمونه را بگیرید.</li>"
    "<li>فایل را با عنوان نام و شماره تلفن و رمزگذاری CSV UTF-8 ذخیره کنید.</li>"
    "<li>فایل را انتخاب و بررسی کنید. درصد پیشرفت برای بررسی و ثبت جداگانه نمایش داده می‌شود.</li>"
    "<li>نتیجه را بررسی و ثبت را تأیید کنید. صفحه را تا پایان باز نگه دارید.</li>"
    "<li>در صورت قطع ثبت، بخش‌های قبلی باقی می‌مانند؛ برای ادامه فایل را با گزینه نادیده گرفتن "
    "شماره‌های موجود دوباره وارد کنید. در حالت به‌روزرسانی، فقط خانه‌های پر جایگزین می‌شوند.</li></ol>"
    "<h2>تأیید رفع مشکل</h2><p>درصد باید به صد برسد؛ شمار مخاطبان جدید، به‌روزشده و خطاها را "
    "در گزارش بررسی کنید. بررسی اولیه هیچ مخاطبی ذخیره نمی‌کند.</p>"
    "<h2>پیشگیری</h2><p>برای فایل سقف حجم و تعداد ردیف وجود ندارد. فایل در بخش‌های کوچک "
    "و پشت‌سرهم ارسال می‌شود؛ زمان لازم به حجم فایل و سرعت شبکه بستگی دارد. "
    "شماره‌های تکراری فایل پس از اولین ردیف معتبر نادیده گرفته می‌شوند.</p>"
)


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "INSERT INTO help_articles (slug, title, summary, body_html, body_plain, kind, "
            "status, position, published_at) VALUES (:slug, :title, :summary, :body, "
            ":summary, 'article', 'published', 150, now()) ON CONFLICT (slug) DO NOTHING"
        ),
        {
            "slug": ARTICLE_SLUG,
            "title": ARTICLE_TITLE,
            "summary": ARTICLE_SUMMARY,
            "body": ARTICLE_BODY,
        },
    )


def downgrade() -> None:
    op.get_bind().execute(
        sa.text("DELETE FROM help_articles WHERE slug = :slug"), {"slug": ARTICLE_SLUG}
    )
