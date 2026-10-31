"""Help content for saved table page sizes."""

import sqlalchemy as sa

from alembic import op

revision = "0090_table_pagination_help_content"
down_revision = "0089_contacts_import_help_content"
branch_labels = None
depends_on = None

ARTICLE_SLUG = "table-pagination-guide"
ARTICLE_TITLE = "تنظیم و ذخیره تعداد ردیف‌های جدول"
ARTICLE_SUMMARY = "نمایش تا ۲۰۰ ردیف در هر صفحه و حفظ انتخاب پس از بارگذاری دوباره."
ARTICLE_BODY = (
    "<h2>تنظیم تعداد نمایش</h2><p>پایین جدول، از فهرست تعداد نمایش یکی از مقدارهای "
    "۱۰، ۲۵، ۵۰، ۱۰۰ یا ۲۰۰ را انتخاب کنید. تغییر تعداد نمایش، جدول‌های همین صفحه را "
    "به صفحه اول برمی‌گرداند و فیلترها را نگه می‌دارد.</p>"
    "<h2>ذخیره و اشتراک‌گذاری</h2><p>انتخاب شما برای همان صفحه در مرورگر ذخیره می‌شود. "
    'تعداد نمایش با پارامتر <code dir="ltr">page_size</code> در آدرس قابل مشاهده است. '
    "مقدار آدرس بر انتخاب ذخیره‌شده اولویت دارد؛ برای اشتراک همان نما، آدرس را کپی کنید.</p>"
    "<h2>نشانه‌ها و علت</h2><p>اگر ذخیره‌سازی مرورگر مسدود باشد، انتخاب فقط در آدرس "
    "حفظ می‌شود. مقدار نامعتبر در آدرس صفحه به انتخاب ذخیره‌شده یا پیش‌فرض ۲۵ بازمی‌گردد. "
    "API برای درخواست تعداد خارج از بازه مجاز، کد "
    '<code dir="ltr">invalid_request</code> برمی‌گرداند.</p>'
    "<h2>رفع مشکل</h2><ol><li>تعداد نمایش را از فهرست انتخاب کنید؛ مقدار آدرس را دستی "
    "بیشتر از ۲۰۰ نگذارید.</li><li>برای حفظ انتخاب در مراجعه بعدی، ذخیره‌سازی مرورگر "
    "را مجاز کنید یا آدرس دارای تعداد نمایش را نشانک بزنید.</li></ol>"
    "<h2>تأیید</h2><p>صفحه را دوباره بارگذاری کنید و مقدار انتخاب‌شده را بررسی کنید. "
    "در جدول‌های دارای داده کافی، با انتخاب ۲۰۰ حداکثر ۲۰۰ ردیف نمایش داده می‌شود؛ "
    "برای ادامه از صفحه بعد استفاده کنید.</p>"
    "<h2>پیشگیری</h2><p>برای دستگاه‌های کند، تعداد کمتری انتخاب کنید. تنظیم بخش ادمین "
    "و مشتری جداگانه ذخیره می‌شود. جدول‌های ثابت راهنما شامل صفحه‌بندی نمی‌شوند.</p>"
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
