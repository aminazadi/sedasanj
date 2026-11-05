"""Help-center article for the first-time Jalase-Negar Android install from the landing page."""

# ruff: noqa: E501 - the article text is long Persian prose that does not wrap usefully

import html

import sqlalchemy as sa

from alembic import op

revision = "0115_jalase_negar_install_help"
down_revision = "0114_primary_organization_admin"
branch_labels = None
depends_on = None

CATEGORY_SLUG = "meetings"
SLUG = "jalase-negar-android-install"
TITLE = "نصب جلسه‌نگار روی گوشی اندروید"
SUMMARY = "دانلود فایل نصب از صفحه اصلی صداسنج، اجازه نصب از مرورگر و اتصال اپ به سازمان."
BLOCKS = [
    "نشانه‌ها: فایل دانلود شد ولی نصب نمی‌شود، اندروید هشدار «منبع ناشناس» می‌دهد یا دکمه دانلود در صفحه اصلی دیده نمی‌شود.",
    "علت: جلسه‌نگار از فروشگاه‌های رسمی اندروید نصب نمی‌شود؛ فایل نصب مستقیم از سرور صداسنج دریافت می‌شود و اندروید برای نصب چنین فایلی از مرورگر، اجازه جداگانه می‌خواهد.",
    [
        "در صفحه اصلی صداسنج، در بخش «اپلیکیشن»، دکمه «دانلود جلسه‌نگار» را بزنید و دانلود را تا پایان نگه دارید.",
        "فایل را از اعلان مرورگر یا پوشه Downloads باز کنید.",
        "اگر اندروید پیام منبع ناشناس داد، «تنظیمات» را بزنید، نصب از همان مرورگر را مجاز کنید و به صفحه نصب برگردید.",
        "«نصب» را بزنید و پس از پایان، جلسه‌نگار را باز کنید.",
        "در اپ، از «تنظیمات» با اسکن QR یا چسباندن متن تنظیمات، به سازمان خود وصل شوید.",
    ],
    "اگر دکمه دانلود دیده نمی‌شود یا پیام «به‌زودی منتشر می‌شود» می‌آید، هنوز نسخه‌ای منتشر نشده است؛ با پشتیبانی تماس بگیرید. اگر «دریافت اطلاعات نسخه انجام نشد» آمد، اینترنت را بررسی کنید و «تلاش دوباره» را بزنید.",
    "برای اطمینان، در «تنظیمات» اپ «بررسی به‌روزرسانی» را بزنید؛ پیام «نسخه شما به‌روز است» یعنی نصب کامل است.",
    "پیشگیری: فایل نصب را فقط از صفحه اصلی صداسنج دانلود کنید و پس از نصب، مجوز نصب از مرورگر را دوباره غیرفعال کنید.",
]


def _body() -> tuple[str, str]:
    parts: list[str] = []
    plain: list[str] = []
    for block in BLOCKS:
        if isinstance(block, list):
            parts.append(
                "<ol>" + "".join(f"<li>{html.escape(step)}</li>" for step in block) + "</ol>"
            )
            plain.extend(block)
        else:
            parts.append(f"<p>{html.escape(block)}</p>")
            plain.append(block)
    return "".join(parts), " ".join(plain)


def upgrade() -> None:
    bind = op.get_bind()
    category_id = bind.execute(
        sa.text("SELECT id FROM help_categories WHERE slug = :slug"), {"slug": CATEGORY_SLUG}
    ).scalar_one()
    body_html, body_plain = _body()
    bind.execute(
        sa.text(
            "INSERT INTO help_articles (slug, category_id, title, summary, body_html, body_plain, "
            "kind, status, position, published_at) "
            "VALUES (:slug, :category, :title, :summary, :html, :plain, 'article', 'published', 22, now()) "
            "ON CONFLICT (slug) DO NOTHING"
        ),
        {
            "slug": SLUG,
            "category": category_id,
            "title": TITLE,
            "summary": SUMMARY,
            "html": body_html,
            "plain": body_plain,
        },
    )


def downgrade() -> None:
    op.get_bind().execute(sa.text("DELETE FROM help_articles WHERE slug = :slug"), {"slug": SLUG})
