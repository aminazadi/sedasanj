"""Store report run titles and charts and publish document export help."""

from html import escape

import sqlalchemy as sa

from alembic import op

revision = "0101_report_documents"
down_revision = "0100_call_asr_rollout"
branch_labels = None
depends_on = None

ARTICLES = (
    (
        "scheduled-report-titles-and-charts",
        "عنوان و نمودارهای گزارش زمان‌بندی‌شده",
        None,
        "",
        (
            "در آرشیو گزارش‌ها، عنوان هر اجرای آماده موضوع همان اجرا را نشان می‌دهد. "
            "نام تعریف زمان‌بندی در جزئیات گزارش باقی می‌ماند. گزارش‌های قبلی با نام قبلی باز می‌شوند.",
            "در معیارهای گزارش، آمار و نمودار دلخواه را بنویسید. برای نمونه، روند روزانه تماس‌ها "
            "را با نمودار خطی یا امتیاز اپراتورها را با نمودار میله‌ای افقی بخواهید.",
            "نوع‌های موجود شامل ستونی، میله‌ای افقی، خطی، سطحی، دایره‌ای، حلقه‌ای، راداری، "
            "میله‌ای شعاعی، پراکندگی، ترکیبی، نقشه درختی و قیفی است. "
            "گزارش فقط با داده‌های آماری موجود در بازه نمودار می‌سازد.",
            "اگر نمودار نمایش داده نمی‌شود، بازه و وجود آمار را بررسی کنید و از مدیر صداسنج بخواهید "
            "در تنظیمات ابزارهای دستیار، ابزار «ترسیم نمودار آماری» را بررسی کند.",
        ),
    ),
    (
        "print-and-download-documents",
        "چاپ و دانلود PDF گزارش و صورت‌جلسه",
        None,
        "",
        (
            "یک گزارش آماده را در آرشیو باز کنید یا به جزئیات جلسه‌ای بروید که صورت‌جلسه دارد. "
            "گزینه «دانلود PDF» فایل فارسی A4 را در مرورگر دانلود می‌کند.",
            "گزینه «چاپ» پیش‌نمایش چاپ را بدون منوهای پنل باز می‌کند. "
            "گزارش در پیش‌نمایش با نمودارهای خودش و در فایل PDF با جدول‌ها و میله‌های آماری چاپی "
            "نمایش داده می‌شود. خروجی جلسه نسخه فعال صورت‌جلسه را در بر دارد.",
            "در پیش‌نمایش اندازه کاغذ A4 را انتخاب کنید. برای یک نسخه PDF با نمودارهای "
            "هم‌شکل پنل می‌توانید مقصد «ذخیره به‌صورت PDF» را در پنجره چاپ انتخاب کنید.",
        ),
    ),
    (
        "error-document-not-ready",
        "گزارش یا صورت‌جلسه برای دریافت آماده نیست",
        "document_not_ready",
        "وضعیت پردازش را در صفحه همان گزارش یا جلسه بررسی کنید.",
        (
            "درخواست دریافت PDF پیش از آماده شدن سند به خطا رسیده است.",
            "گزارش باید با موفقیت اجرا شده باشد یا جلسه باید صورت‌جلسه آماده داشته باشد.",
            "به آرشیو گزارش‌ها یا جزئیات جلسه برگردید و وضعیت را بررسی کنید. "
            "اگر پردازش ناموفق است، دلیل نمایش‌داده‌شده در پنل را بررسی کنید.",
            "پس از آماده شدن سند، دکمه «دانلود PDF» را بزنید و عنوان فایل را بررسی کنید.",
        ),
    ),
    (
        "error-document-pdf-unavailable",
        "آماده‌سازی فایل PDF ممکن نشد",
        "document_pdf_unavailable",
        "دوباره تلاش کنید یا از گزینه چاپ مرورگر استفاده کنید.",
        (
            "دانلود سند آماده با خطای ساخت PDF روبه‌رو شده است.",
            "ممکن است آماده‌سازی فایل در سرور موقتاً در دسترس نباشد.",
            "دانلود را دوباره امتحان کنید. در صورت تکرار، گزینه «چاپ» را بزنید و در مرورگر "
            "مقصد ذخیره PDF را انتخاب کنید. برای بررسی، کد خطا را به پشتیبانی بدهید.",
            "فایل ذخیره‌شده را باز کنید و عنوان، صفحه‌بندی و متن فارسی را بررسی کنید.",
        ),
    ),
)


def upgrade() -> None:
    op.execute("ALTER TABLE scheduled_report_runs ADD COLUMN title varchar(200)")
    op.execute(
        "ALTER TABLE scheduled_report_runs ADD COLUMN charts jsonb NOT NULL DEFAULT '[]'::jsonb"
    )
    bind = op.get_bind()
    for slug, title, code, action, paragraphs in ARTICLES:
        bind.execute(
            sa.text(
                "INSERT INTO help_articles "
                "(slug, title, summary, body_html, body_plain, kind, status, published_at) "
                "VALUES (:slug, :title, :summary, :html, :plain, :kind, 'published', now()) "
                "ON CONFLICT (slug) DO NOTHING"
            ),
            {
                "slug": slug,
                "title": title,
                "summary": paragraphs[0],
                "html": "".join(f"<p>{escape(paragraph)}</p>" for paragraph in paragraphs),
                "plain": "\n".join(paragraphs),
                "kind": "error" if code else "article",
            },
        )
        if code:
            bind.execute(
                sa.text(
                    "INSERT INTO help_error_codes "
                    "(code, article_id, source, severity, title, quick_action) "
                    "SELECT :code, id, 'api', 'warning', :title, :action FROM help_articles "
                    "WHERE slug = :slug ON CONFLICT (code) DO NOTHING"
                ),
                {"code": code, "slug": slug, "title": title, "action": action},
            )


def downgrade() -> None:
    bind = op.get_bind()
    for slug, _, code, _, _ in ARTICLES:
        if code:
            bind.execute(
                sa.text(
                    "DELETE FROM help_error_codes WHERE code = :code AND article_id = "
                    "(SELECT id FROM help_articles WHERE slug = :slug)"
                ),
                {"code": code, "slug": slug},
            )
        bind.execute(sa.text("DELETE FROM help_articles WHERE slug = :slug"), {"slug": slug})
    op.execute("ALTER TABLE scheduled_report_runs DROP COLUMN charts")
    op.execute("ALTER TABLE scheduled_report_runs DROP COLUMN title")
