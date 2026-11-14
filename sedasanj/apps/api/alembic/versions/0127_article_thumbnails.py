"""Add optional article thumbnails backed by the help media library."""

import sqlalchemy as sa

from alembic import op

revision = "0127_article_thumbnails"
down_revision = "0126_provider_unreachable_help"
branch_labels = None
depends_on = None


SLUG = "article-thumbnails"
TITLE = "تعیین تصویر بندانگشتی مقاله"
BODY = (
    "<h2>روش استفاده</h2><p>در ویرایش مقاله، بخش تصویر بندانگشتی را باز کنید. "
    "انتخاب یا آپلود تصویر را بزنید، تصویر افقی انتخاب کنید و مقاله را ذخیره کنید.</p>"
    "<h2>محل نمایش</h2><p>تصویر در کارت صفحهٔ اصلی، فهرست و جستجو، مقالات مرتبط "
    "و بالای مقاله نمایش داده می‌شود. مقالهٔ بدون تصویر همچنان قابل نمایش است.</p>"
    "<h2>رفع خطا</h2><p>اگر invalid_request دیدید، یک تصویر موجود در کتابخانه "
    "انتخاب کنید؛ ویدئو قابل انتخاب نیست. اگر حذف فایل با conflict_idempotency رد شد، "
    "ابتدا آن را از متن و بندانگشتی تمام مقاله‌ها بردارید و ذخیره کنید.</p>"
    "<h2>بررسی</h2><p>پس از ذخیره، صفحهٔ مقاله و کارت آن را بازآوری کنید. "
    "برای برداشتن تصویر، حذف تصویر بندانگشتی و سپس ذخیره را بزنید؛ فایل اصلی باقی می‌ماند.</p>"
)


def upgrade() -> None:
    op.execute(
        "ALTER TABLE help_articles ADD COLUMN thumbnail_id uuid "
        "REFERENCES help_media(id) ON DELETE SET NULL"
    )

    op.get_bind().execute(
        sa.text(
            "INSERT INTO help_articles (slug, title, summary, body_html, body_plain, kind, "
            "status, position, published_at) VALUES (:slug, :title, :summary, :body, "
            ":plain, 'article', 'published', 152, now()) ON CONFLICT (slug) DO NOTHING"
        ),
        {"slug": SLUG, "title": TITLE, "summary": TITLE, "body": BODY, "plain": TITLE},
    )


def downgrade() -> None:
    op.get_bind().execute(sa.text("DELETE FROM help_articles WHERE slug = :slug"), {"slug": SLUG})
    op.execute("ALTER TABLE help_articles DROP COLUMN thumbnail_id")
