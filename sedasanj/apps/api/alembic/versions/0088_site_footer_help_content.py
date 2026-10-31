"""Help content for admin-managed public footer settings."""

import sqlalchemy as sa

from alembic import op

revision = "0088_site_footer_help_content"
down_revision = "0087_internal_calls"
branch_labels = None
depends_on = None

ARTICLE_SLUG = "site-footer-settings-guide"
ARTICLE_TITLE = "مدیریت لینک‌ها و توضیحات فوتر"
ARTICLE_SUMMARY = "ویرایش متن‌ها، ترتیب لینک‌ها و نمادهای فوتر تمام صفحات عمومی از تنظیمات ادمین."
ARTICLE_BODY = (
    "<h2>نشانه‌ها</h2><p>متن یا لینک فوتر نیاز به تغییر دارد یا ذخیرهٔ تنظیمات با خطای "
    '<code dir="ltr">invalid_request</code> رد می‌شود.</p>'
    "<h2>علت</h2><p>عنوان لینک نباید خالی باشد. هر گروه حداکثر ۳۰ لینک دارد و نشانی باید "
    "مسیر داخلی یا نشانی کامل وب باشد؛ اسکریپت و نشانی دارای فاصله پذیرفته نمی‌شود.</p>"
    "<h2>رفع مشکل</h2><ol><li>در پنل ادمین، تنظیمات و سپس تنظیمات سایت را باز کنید.</li>"
    "<li>عنوان‌ها، توضیحات معرفی و تماس، متن پایین فوتر و شماره تماس را ویرایش کنید. "
    "برای حذف متن، فیلد مربوط را خالی بگذارید.</li>"
    "<li>در هر گروه، لینک اضافه یا حذف کنید و با دکمه‌های بالا و پایین ترتیب را تغییر دهید.</li>"
    '<li>برای لینک داخلی از <code dir="ltr">/about</code> و برای لینک بیرونی از '
    '<code dir="ltr">https://example.com</code> استفاده کنید. عنوان و نشانی همهٔ لینک‌ها '
    "را کامل کنید و ذخیره تنظیمات سایت را بزنید.</li>"
    "<li>کد نمادها همچنان در فیلد جداگانه ذخیره و داخل قاب ایزوله نمایش داده می‌شود.</li></ol>"
    "<h2>تأیید رفع مشکل</h2><p>پس از پیام ذخیره، صفحه اصلی و یکی از صفحات عمومی را بازآوری "
    "کنید و متن‌ها، مقصد و ترتیب لینک‌ها را بررسی کنید. تنظیمات ادمین را دوباره باز کنید "
    "تا ماندگاری تغییرات تأیید شود.</p>"
    "<h2>پیشگیری</h2><p>پیش از ذخیره، مقصد لینک‌ها را بررسی کنید. حذف تمام لینک‌های یک گروه، "
    "آن گروه را خالی نگه می‌دارد و لینک‌های پیش‌فرض برنمی‌گردند.</p>"
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
