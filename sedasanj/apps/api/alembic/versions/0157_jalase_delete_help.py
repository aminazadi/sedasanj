"""Help for deleting a personal Jalase-Negar account."""

# ruff: noqa: E501 - Persian help prose is kept in complete paragraphs.

import sqlalchemy as sa

from alembic import op

revision = "0157_jalase_delete_help"
down_revision = "0156_jalase_import_help"
branch_labels = None
depends_on = None

SLUG = "jalase-negar-delete-account"
CODE = "account_delete_mismatch"
TITLE = "حذف حساب جلسه‌نگار"
SUMMARY = "حذف همیشگی حساب شخصی جلسه‌نگار با تأیید پیامکی و آنچه حذف می‌شود."
BODY = (
    "<h2>حذف حساب چه می‌کند</h2><p>در اپ از «تنظیمات ← حذف حساب» با تأیید کد پیامکی شمارهٔ خودتان، حساب را حذف می‌کنید. همهٔ جلسه‌ها، متن‌ها و اسناد شما پاک می‌شوند، همهٔ دستگاه‌ها و اتصال‌های سازمانی از کار می‌افتند و اشتراک فعال لغو می‌شود. برای ماه پرداخت‌شده بازپرداخت انجام نمی‌شود. جلسه‌هایی که پیش‌تر در سازمان صداسنج ذخیره شده‌اند، دادهٔ همان سازمان‌اند و پاک نمی‌شوند. این کار برگشت‌پذیر نیست.</p>"
    '<h2>خطا</h2><p><code dir="ltr">account_delete_mismatch</code>: شمارهٔ تأییدشده با شمارهٔ حساب یکی نیست.</p>'
    "<h2>رفع مشکل</h2><ol><li>کد پیامکی را با همان شمارهٔ ورود به جلسه‌نگار بگیرید.</li>"
    "<li>اگر شمارهٔ شما تغییر کرده، با پشتیبانی تماس بگیرید.</li></ol>"
    "<h2>تأیید</h2><p>پس از حذف، اپ از حساب خارج می‌شود و ورود با همان شماره یک حساب تازهٔ خالی می‌سازد.</p>"
)


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "INSERT INTO help_articles (slug,title,summary,body_html,body_plain,kind,status,"
            "position,published_at) "
            "VALUES (:slug,:title,:summary,:body,:summary,'article','published',157,now()) "
            "ON CONFLICT (slug) DO NOTHING"
        ),
        {"slug": SLUG, "title": TITLE, "summary": SUMMARY, "body": BODY},
    )
    bind.execute(
        sa.text(
            "INSERT INTO help_error_codes (code,source,severity,article_id,title,quick_action) "
            "SELECT :code,'api','error',id,:title,:action "
            "FROM help_articles WHERE slug=:slug ON CONFLICT (code) DO NOTHING"
        ),
        {
            "slug": SLUG,
            "code": CODE,
            "title": "شمارهٔ تأییدشده با شمارهٔ حساب یکی نیست.",
            "action": "کد را با همان شمارهٔ ورود بگیرید.",
        },
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM help_error_codes WHERE code=:code"), {"code": CODE})
    bind.execute(sa.text("DELETE FROM help_articles WHERE slug=:slug"), {"slug": SLUG})
