"""Seed the help article that explains categories, archive and pagination."""

import sqlalchemy as sa

from alembic import op

revision = "0128_help_categories_archive"
down_revision = "0127_article_thumbnails"
branch_labels = None
depends_on = None

SLUG = "help-categories-archive"
TITLE = "دسته‌بندی، آرشیو و صفحه‌بندی مقاله‌ها"
BODY = (
    "<h2>تعیین دسته</h2><p>در ویرایش مقاله، فیلد دسته را انتخاب و ذخیره کنید. "
    "دسته‌ها از بخش دسته‌ها در پنل مدیریت ساخته و مرتب می‌شوند.</p>"
    "<h2>نمایش در مرکز راهنما</h2><p>فقط دسته‌هایی که دست‌کم یک مقالهٔ منتشرشده دارند "
    "نمایش داده می‌شوند. با انتخاب یک دسته، فهرست مقاله‌ها فیلتر می‌شود و پیوند صفحه "
    "قابل اشتراک است.</p>"
    "<h2>آرشیو و صفحه‌بندی</h2><p>آرشیو مقاله‌ها را بر اساس ماه شمسی انتشار گروه‌بندی "
    "می‌کند. فهرست در هر صفحه ۱۲ مقاله نشان می‌دهد و با شماره صفحه‌ها جابه‌جا می‌شوید.</p>"
    "<h2>رفع خطا</h2><p>اگر مقاله‌ای دیده نمی‌شود، وضعیت آن را منتشرشده کنید. "
    "اگر خطای invalid_request دیدید، ماه آرشیو را به شکل 1405-08 بدهید.</p>"
)


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "INSERT INTO help_articles (slug, title, summary, body_html, body_plain, kind, "
            "status, position, published_at) VALUES (:slug, :title, :summary, :body, "
            ":plain, 'article', 'published', 153, now()) ON CONFLICT (slug) DO NOTHING"
        ),
        {"slug": SLUG, "title": TITLE, "summary": TITLE, "body": BODY, "plain": TITLE},
    )


def downgrade() -> None:
    op.get_bind().execute(sa.text("DELETE FROM help_articles WHERE slug = :slug"), {"slug": SLUG})
