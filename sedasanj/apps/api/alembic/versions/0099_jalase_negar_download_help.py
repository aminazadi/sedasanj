"""Add help for downloading the published Jalase-Negar APK from Meetings."""

import sqlalchemy as sa

from alembic import op

revision = "0099_jalase_negar_download_help"
down_revision = "0098_jalase_negar_update_help_content"
branch_labels = None
depends_on = None

SLUG = "meetings-download-jalase-negar"
TITLE = "دانلود جلسه‌نگار از صفحه جلسات"
ERROR_CODE = "jalase_negar_release_not_found"
PARAGRAPHS = (
    "در پنل صداسنج، صفحه «جلسات» را باز کنید و کنار دکمه فیلتر «دانلود اپلیکیشن» را بزنید.",
    "آخرین نسخه‌ای که مدیر صداسنج منتشر کرده است به‌صورت فایل APK برای اندروید دانلود می‌شود. "
    "پس از پایان دانلود، فایل را در گوشی اندرویدی باز کنید.",
    "اگر هنوز نسخه‌ای منتشر نشده است، بعد از انتشار نسخه دوباره امتحان کنید. "
    "اگر فایل موقتاً در دسترس نیست، چند دقیقه صبر کنید و دکمه را دوباره بزنید. "
    "اگر همچنان دانلود شروع نشد، با پشتیبانی صداسنج تماس بگیرید.",
    "برای اطمینان از پایان دانلود، فایل جلسه‌نگار را در فهرست دانلودهای مرورگر پیدا کنید.",
)


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "INSERT INTO help_articles (slug, category_id, title, summary, body_html, body_plain, "
            "kind, status, position, published_at) "
            "SELECT :slug, id, :title, :summary, :html, :plain, 'article', 'published', 12, now() "
            "FROM help_categories WHERE slug = 'meetings' ON CONFLICT (slug) DO NOTHING"
        ),
        {
            "slug": SLUG,
            "title": TITLE,
            "summary": PARAGRAPHS[0],
            "html": "".join(f"<p>{paragraph}</p>" for paragraph in PARAGRAPHS),
            "plain": " ".join(PARAGRAPHS),
        },
    )
    bind.execute(
        sa.text(
            "INSERT INTO help_error_codes "
            "(code, article_id, source, severity, title, quick_action) "
            "SELECT :code, id, 'api', 'warning', :title, :action FROM help_articles "
            "WHERE slug = :slug ON CONFLICT (code) DO NOTHING"
        ),
        {
            "code": ERROR_CODE,
            "slug": SLUG,
            "title": "نسخه‌ای از جلسه‌نگار منتشر نشده است",
            "action": "بعد از انتشار نسخه دوباره امتحان کنید.",
        },
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "DELETE FROM help_error_codes WHERE code = :code AND article_id = "
            "(SELECT id FROM help_articles WHERE slug = :slug)"
        ),
        {"code": ERROR_CODE, "slug": SLUG},
    )
    bind.execute(sa.text("DELETE FROM help_articles WHERE slug = :slug"), {"slug": SLUG})
