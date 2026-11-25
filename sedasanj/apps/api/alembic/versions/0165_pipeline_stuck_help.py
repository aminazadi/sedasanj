"""Help for calls whose pipeline step stalled, was cancelled or timed out."""

# ruff: noqa: E501 - Persian help prose is kept in complete paragraphs.

import sqlalchemy as sa

from alembic import op

revision = "0165_pipeline_stuck_help"
down_revision = "0164_call_pipeline_indexes"
branch_labels = None
depends_on = None

SLUG = "call-processing-stalled"
TITLE = "تماس در مرحله پردازش متوقف شد"
SUMMARY = (
    "وقتی یک مرحله از پردازش تماس (پیاده‌سازی، تصحیح متن، تحلیل یا اطلاع‌رسانی) "
    "ناتمام بماند، سرور خودکار آن را از سر می‌گیرد یا تماس را با خطای مشخص متوقف می‌کند."
)
BODY = (
    "<h2>نشانه</h2><p>در گزارش اجرای پردازش، یکی از این کدها دیده می‌شود: "
    '<code dir="ltr">job_cancelled</code>، <code dir="ltr">job_superseded</code>، '
    '<code dir="ltr">job_call_state_mismatch</code> یا <code dir="ltr">processing_timeout</code>. '
    "این کدها روی خود پردازش ثبت می‌شوند و برای کاربر نهایی فقط توضیح وضعیت تماس اهمیت دارد.</p>"
    "<h2>بازیابی خودکار</h2><p>اگر اجرای یک مرحله پیش از پایان متوقف شود (برای نمونه بازراه‌اندازی "
    "سرور یا پایان مهلت پردازش)، سرور همان کار را دوباره در صف می‌گذارد و پردازش از همان مرحله "
    "ادامه پیدا می‌کند. کاری که تکراری در صف مانده باشد بسته می‌شود تا جلوی پردازش بقیه تماس‌ها "
    "را نگیرد؛ نتیجه در گزارش اجرای پردازش دیده می‌شود.</p>"
    "<h2>توقف نهایی</h2><p>اگر مرحله بعدی پردازش دیگر قابل بازیابی نباشد، یا پردازش از مهلت مجاز "
    "طولانی‌تر شود، تماس با وضعیت «خطای نهایی» متوقف می‌شود و اعتبار رزروشدهٔ آن آزاد می‌شود. "
    "در این حالت از دکمهٔ «پردازش مجدد» در صفحهٔ تماس استفاده کنید.</p>"
    "<h2>رفع مشکل</h2><ol><li>وضعیت سرویس تحلیل و اتصال آن را در صفحهٔ تنظیمات بررسی کنید.</li>"
    "<li>در صفحهٔ تماس، گزارش اجرای پردازش را باز کنید و کد خطا را ببینید.</li>"
    "<li>پس از رفع علت، «پردازش مجدد» را بزنید؛ اعتبار فقط یک بار کم می‌شود.</li></ol>"
)

CODES = (
    (
        "job_cancelled",
        "warning",
        "اجرای مرحله پردازش پیش از پایان متوقف شد.",
        "نیازی به کار نیست؛ سرور همین مرحله را خودکار از سر می‌گیرد.",
    ),
    (
        "job_superseded",
        "warning",
        "کار تکراری در صف بسته شد.",
        "نیازی به کار نیست؛ جدیدترین کار همان مرحله در حال اجراست.",
    ),
    (
        "job_call_state_mismatch",
        "error",
        "کار در صف ماند چون وضعیت تماس دیگر آن را نمی‌پذیرد.",
        "از صفحهٔ تماس «پردازش مجدد» را بزنید.",
    ),
    (
        "processing_timeout",
        "error",
        "پردازش تماس از مهلت مجاز طولانی‌تر شد و متوقف شد.",
        "اتصال سرویس تحلیل را بررسی کنید و سپس «پردازش مجدد» را بزنید.",
    ),
)


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "INSERT INTO help_articles (slug,title,summary,body_html,body_plain,kind,status,"
            "position,published_at) "
            "VALUES (:slug,:title,:summary,:body,:summary,'article','published',165,now()) "
            "ON CONFLICT (slug) DO NOTHING"
        ),
        {"slug": SLUG, "title": TITLE, "summary": SUMMARY, "body": BODY},
    )
    for code, severity, title, action in CODES:
        bind.execute(
            sa.text(
                "INSERT INTO help_error_codes (code,source,severity,article_id,title,quick_action) "
                "SELECT :code,'worker',:severity,id,:title,:action "
                "FROM help_articles WHERE slug=:slug ON CONFLICT (code) DO NOTHING"
            ),
            {
                "slug": SLUG,
                "code": code,
                "severity": severity,
                "title": title,
                "action": action,
            },
        )


def downgrade() -> None:
    bind = op.get_bind()
    for code, *_ in CODES:
        bind.execute(sa.text("DELETE FROM help_error_codes WHERE code=:code"), {"code": code})
    bind.execute(sa.text("DELETE FROM help_articles WHERE slug=:slug"), {"slug": SLUG})
