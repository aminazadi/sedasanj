"""Publish the footer social links guide."""

import sqlalchemy as sa

from alembic import op

revision = "0123_footer_address_help"
down_revision = "0122_footer_social_links_help"
branch_labels = None
depends_on = None

SLUG = "footer-address"
TITLE = "نمایش نشانی در فوتر"
SUMMARY = "ثبت یا حذف نشانی نمایش‌داده‌شده در فوتر صفحهٔ عمومی از تنظیمات سایت."
BODY = (
    "<h2>نشانه‌ها</h2><p>نشانی در فوتر دیده نمی‌شود یا ذخیره با خطای "
    '<code dir="ltr">invalid_request</code> رد می‌شود.</p>'
    "<h2>علت</h2><p>فیلد نشانی خالی است، یا متن آن از ۵۰۰ نویسه بلندتر است.</p>"
    "<h2>رفع مشکل</h2><ol>"
    "<li>در پنل ادمین، تنظیمات ← تنظیمات سایت ← محتوای فوتر را باز کنید.</li>"
    "<li>نشانی را در فیلد «نشانی» وارد کنید. هر خط جدید در فوتر هم در خط جدید دیده می‌شود.</li>"
    "<li>برای پنهان کردن نشانی، فیلد را خالی بگذارید و تنظیمات را ذخیره کنید.</li>"
    "</ol><h2>تأیید رفع مشکل</h2><p>صفحهٔ عمومی را بازآوری کنید. نشانی باید زیر "
    "توضیح کوتاه فوتر دیده شود.</p>"
    "<h2>پیشگیری</h2><p>نشانی را کوتاه و دقیق بنویسید و هنگام جابه‌جایی دفتر، آن را "
    "به‌روز کنید.</p>"
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
