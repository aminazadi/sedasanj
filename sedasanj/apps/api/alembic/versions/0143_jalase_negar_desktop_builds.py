"""Add Windows/macOS installer uploads for the Jalase-Negar download dialog, with help."""

# ruff: noqa: E501 - the article text is long Persian prose that does not wrap usefully

import sqlalchemy as sa

from alembic import op

revision = "0143_jalase_negar_desktop_builds"
down_revision = "0142_call_asr_model_help"
branch_labels = None
depends_on = None

SLUG = "jalase-negar-download-dialog"
TITLE = "دانلود جلسه‌نگار برای اندروید، ویندوز، مک و فروشگاه‌ها"
PARAGRAPHS = (
    "با زدن دکمهٔ «دانلود جلسه‌نگار» در صفحهٔ اصلی، پنجره‌ای با همهٔ راه‌های دریافت اپ باز می‌شود: "
    "فایل مستقیم اندروید، نسخهٔ ویندوز، نسخهٔ مک و لینک فروشگاه‌ها (کافه‌بازار، مایکت، گوگل‌پلی، "
    "اپ‌استور، اناردونی و سیب‌اپ). اگر فقط نسخهٔ اندروید در دسترس باشد، دکمه مستقیم دانلود را شروع می‌کند.",
    "مدیر ارشد در پنل ادمین، بخش «دانلود جلسه‌نگار»، لینک هر فروشگاه را وارد می‌کند. لینک باید با https شروع شود؛ "
    "فروشگاهی که لینکش خالی باشد نمایش داده نمی‌شود.",
    "برای ویندوز یا مک، پلتفرم و شمارهٔ نسخه را انتخاب کنید و فایل نصب را بارگذاری کنید "
    "(ویندوز: exe، msi یا zip؛ مک: dmg، pkg یا zip). جدیدترین فایل هر پلتفرم در پنجرهٔ دانلود نمایش داده می‌شود. "
    "اثر انگشت SHA-256 فایل در پنل نشان داده می‌شود تا درستی دانلود قابل بررسی باشد.",
    "اگر بارگذاری رد شد، پسوند فایل، شمارهٔ نسخه و اندازهٔ فایل را بررسی کنید و دوباره تلاش کنید. "
    "اگر ذخیره‌سازی فایل در دسترس نیست، چند دقیقه بعد دوباره بارگذاری کنید.",
)


def upgrade() -> None:
    op.execute("""CREATE TABLE jalase_negar_desktop_builds (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    platform VARCHAR(8) NOT NULL,
    version_name VARCHAR(32) NOT NULL,
    file_name VARCHAR(128) NOT NULL,
    artifact_key TEXT NOT NULL,
    artifact_sha256 VARCHAR(64) NOT NULL,
    artifact_size BIGINT NOT NULL,
    created_by UUID,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT jalase_negar_desktop_builds_platform_check CHECK (platform IN ('windows','macos')),
    FOREIGN KEY(created_by) REFERENCES staff_users (id) ON DELETE SET NULL
)""")
    op.execute(
        "CREATE INDEX idx_jalase_negar_desktop_builds_platform "
        "ON jalase_negar_desktop_builds (platform, created_at DESC)"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON jalase_negar_desktop_builds TO cbi_app")
    op.get_bind().execute(
        sa.text(
            "INSERT INTO help_articles (slug, category_id, title, summary, body_html, body_plain, "
            "kind, status, position, published_at) "
            "SELECT :slug, id, :title, :summary, :html, :plain, 'article', 'published', 13, now() "
            "FROM help_categories WHERE slug = 'meetings' ON CONFLICT (slug) DO NOTHING"
        ),
        {
            "slug": SLUG,
            "title": TITLE,
            "summary": PARAGRAPHS[0],
            "html": "".join(f"<p>{p}</p>" for p in PARAGRAPHS),
            "plain": " ".join(PARAGRAPHS),
        },
    )


def downgrade() -> None:
    op.get_bind().execute(sa.text("DELETE FROM help_articles WHERE slug = :slug"), {"slug": SLUG})
    op.drop_table("jalase_negar_desktop_builds")
