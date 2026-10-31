"""Add Issabel release compatibility, host profiles and actionable help pages."""

import html

import sqlalchemy as sa

from alembic import op

revision = "0071_issabel_modules"
down_revision = "0070_calls_search_trgm_indexes"
branch_labels = None
depends_on = None

ERRORS = {
    "SS-SYS-1010": (
        "پروفایل ایزابل پشتیبانی نمی‌شود",
        "نسخه ایزابل و چارچوب PBX را با جدول سازگاری تطبیق دهید.",
    ),
    "SS-SYS-1011": (
        "اجرای PHP مستقل ناموفق است",
        "مسیر PHP CLI و افزونه‌های آن را بررسی و فعال‌سازی را دوباره اجرا کنید.",
    ),
    "SS-SYS-1012": (
        "فعال‌سازی یا بازگردانی ناموفق است",
        "صحت بکاپ را بررسی و راهنمای بازگردانی نصب را اجرا کنید.",
    ),
    "SS-HOOK-1010": (
        "ساختار ضبط ایزابل ناسازگار است",
        "فرمان پس از ضبط قبلی و نسخه core را بررسی کنید؛ سپس فعال‌سازی را تکرار کنید.",
    ),
    "SS-HOOK-1011": (
        "آماده‌سازی ضبط ایزابل ناموفق است",
        "مجوز پوشه ضبط و صف، فایل اصلی و فضای آزاد را بررسی کنید.",
    ),
    "SS-UPD-1010": (
        "بسته به‌روزرسانی ایزابل پذیرفته نشد",
        "بسته بتای مخصوص ایزابل، کلید امضا، ساعت و نسخه میزبان را بررسی کنید.",
    ),
}


def upgrade() -> None:
    for column, kind in (
        ("lab_verified", "BOOLEAN NOT NULL DEFAULT false"),
        ("lab_evidence", "TEXT"),
        ("archive_format", "VARCHAR(8) NOT NULL DEFAULT 'zip'"),
        ("min_issabel_major", "INTEGER"),
        ("max_issabel_major", "INTEGER"),
    ):
        op.execute(f"ALTER TABLE module_releases ADD COLUMN {column} {kind}")
    for column, kind in (
        ("issabel_version", "VARCHAR(64)"),
        ("framework_version", "VARCHAR(64)"),
        ("php_web_version", "VARCHAR(32)"),
    ):
        op.execute(f"ALTER TABLE module_installations ADD COLUMN {column} {kind}")
    op.execute(
        "ALTER TABLE module_releases ADD CONSTRAINT module_releases_issabel_range CHECK "
        "((min_issabel_major IS NULL OR min_issabel_major BETWEEN 4 AND 5) AND "
        "(max_issabel_major IS NULL OR max_issabel_major BETWEEN 4 AND 5) AND "
        "(min_issabel_major IS NULL OR max_issabel_major IS NULL OR "
        "min_issabel_major <= max_issabel_major))"
    )
    bind = op.get_bind()
    for code, (title, action) in ERRORS.items():
        slug = "error-" + code.lower()
        body = (
            "<h2>نشانه‌ها</h2><p>" + html.escape(title) + "</p>"
            "<h2>علت</h2><p>پیش‌نیاز یا ساختار میزبان با پروفایل تأییدشده مطابقت ندارد.</p>"
            "<h2>رفع مشکل</h2><ol><li>" + html.escape(action) + "</li>"
            "<li>از تنظیمات و فایل‌های در صف بکاپ بگیرید و بررسی سلامت را اجرا کنید.</li></ol>"
            "<h2>تأیید رفع مشکل</h2><p>یک تماس آزمایشی برقرار کنید؛ "
            "پخش در ایزابل و دریافت در صداسنج را بررسی کنید.</p>"
            "<h2>پیشگیری</h2><p>ابتدا نسخه بتا را در محیط آزمایش نصب کنید "
            "و PHP وب را جایگزین نکنید.</p>"
        )
        bind.execute(
            sa.text(
                "INSERT INTO help_articles (slug, title, summary, body_html, body_plain, kind, "
                "status, position, published_at) VALUES (:slug, :title, :action, :body, :action, "
                "'error', 'published', 120, now()) ON CONFLICT (slug) DO NOTHING"
            ),
            {"slug": slug, "title": title, "action": action, "body": body},
        )
        bind.execute(
            sa.text(
                "INSERT INTO help_error_codes (code, article_id, source, severity, title, "
                "quick_action) SELECT :code, id, 'module', 'error', :title, :action "
                "FROM help_articles WHERE slug = :slug ON CONFLICT (code) DO NOTHING"
            ),
            {"code": code, "slug": slug, "title": title, "action": action},
        )


def downgrade() -> None:
    bind = op.get_bind()
    for code in ERRORS:
        bind.execute(sa.text("DELETE FROM help_error_codes WHERE code = :code"), {"code": code})
        bind.execute(
            sa.text("DELETE FROM help_articles WHERE slug = :slug"),
            {"slug": "error-" + code.lower()},
        )
    op.execute("ALTER TABLE module_releases DROP CONSTRAINT module_releases_issabel_range")
    for column in (
        "lab_verified",
        "lab_evidence",
        "archive_format",
        "min_issabel_major",
        "max_issabel_major",
    ):
        op.execute(f"ALTER TABLE module_releases DROP COLUMN {column}")
    for column in ("issabel_version", "framework_version", "php_web_version"):
        op.execute(f"ALTER TABLE module_installations DROP COLUMN {column}")
