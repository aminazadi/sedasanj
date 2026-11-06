"""Publish the footer social links guide."""

import sqlalchemy as sa

from alembic import op

revision = "0122_footer_social_links_help"
down_revision = "0121_jalase_sound_events_help"
branch_labels = None
depends_on = None

SLUG = "footer-social-links"
TITLE = "نمایش شبکه‌های اجتماعی در فوتر"
SUMMARY = "ثبت لینک ایتا، بله، تلگرام، اینستاگرام، آپارات و یوتیوب در تنظیمات سایت."
BODY = (
    "<h2>نشانه‌ها</h2><p>آیکن شبکه در فوتر دیده نمی‌شود یا ذخیره با خطای "
    '<code dir="ltr">invalid_request</code> رد می‌شود.</p>'
    "<h2>علت</h2><p>فیلد خالی آیکن را پنهان می‌کند. لینک هر شبکه باید نشانی کامل "
    "و معتبر HTTPS باشد.</p>"
    "<h2>رفع مشکل</h2><ol>"
    "<li>در پنل ادمین، تنظیمات ← تنظیمات سایت ← محتوای فوتر را باز کنید.</li>"
    "<li>در بخش شبکه‌های اجتماعی، نشانی صفحه یا کانال رسمی خود را در فیلد همان شبکه "
    'وارد کنید. برای نمونه <code dir="ltr">https://t.me/your_channel</code>.</li>'
    "<li>برای پنهان کردن هر آیکن، فیلد آن شبکه را خالی بگذارید و تنظیمات را ذخیره کنید.</li>"
    "</ol><h2>تأیید رفع مشکل</h2><p>صفحهٔ عمومی را بازآوری کنید. آیکن‌های فعال را "
    "زیر توضیح کوتاه فوتر پیدا کنید و مقصد هر لینک را بررسی کنید.</p>"
    "<h2>پیشگیری</h2><p>لینک را از صفحهٔ رسمی خود کپی کنید و هنگام تغییر نشانی کانال "
    "یا صفحه، تنظیمات فوتر را به‌روز کنید.</p>"
)


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "INSERT INTO help_articles (slug, title, summary, body_html, body_plain, kind, "
            "status, position, published_at) VALUES (:slug, :title, :summary, :body, "
            ":summary, 'article', 'published', 151, now()) ON CONFLICT (slug) DO NOTHING"
        ),
        {"slug": SLUG, "title": TITLE, "summary": SUMMARY, "body": BODY},
    )


def downgrade() -> None:
    op.get_bind().execute(sa.text("DELETE FROM help_articles WHERE slug = :slug"), {"slug": SLUG})
