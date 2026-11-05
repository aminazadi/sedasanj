"""Publish document editing, sharing, and conflict recovery help."""

from html import escape

import sqlalchemy as sa

from alembic import op

revision = "0105_document_editing_help"
down_revision = "0104_pbx_call_parties"
branch_labels = None
depends_on = None

CATEGORY = "document-workspace"
GUIDE = "edit-print-share-documents"
ERROR = "document_edit_conflict"
ERROR_SLUG = "error-document-edit-conflict"
OLD_PDF_DESCRIPTION = "و در فایل PDF با جدول‌ها و میله‌های آماری چاپی"
NEW_PDF_DESCRIPTION = "و در فایل PDF با همان نمودارهای پنل"
STEPS = (
    "صورت‌جلسه کامل یا گزارش آماده را باز کنید. مدیر سازمان می‌تواند گزارش را ویرایش کند؛ "
    "ویرایش صورت‌جلسه برای کاربران دارای دسترسی مدیریت جلسه در دسترس است.",
    "متن را در ویرایشگر فارسی تغییر دهید. "
    "از نوار ابزار برای تیتر، فهرست، پیوند و جدول استفاده کنید. "
    "با اولین تغییر، دکمه «ذخیره تغییرات» در مرکز پایین صفحه ظاهر می‌شود.",
    "پیش از خروج ذخیره کنید. تغییر تب جلسه متن ویرایش‌شده را حفظ می‌کند. "
    "خطای ذخیره متن را پاک نمی‌کند. تغییرات سند در سابقه ممیزی ثبت می‌شوند.",
    "«دانلود PDF» و «چاپ» متن فعلی و نمودارهای خود سند را با قلم محلی و سبک صفحه نمایش "
    "خروجی می‌گیرند. ویرایش ذخیره‌نشده هم در خروجی فعلی دیده می‌شود، اما برای نگهداری در سامانه "
    "باید ذخیره تغییرات را بزنید.",
    "برای اشتراک‌گذاری، دکمه «اشتراک‌گذاری» و پس از آماده شدن فایل، «ارسال فایل PDF» را بزنید. "
    "اگر مرورگر اشتراک فایل را پشتیبانی نکند، PDF دانلود می‌شود؛ فایل را از پیام‌رسان ارسال کنید. "
    "فقط دریافت‌کننده‌ای را انتخاب کنید که باید متن سند را ببیند.",
    "در چاپ A4، مقیاس پیش‌فرض و رنگ پس‌زمینه را فعال کنید. "
    "PDF مستقیم تصویری است؛ برای PDF با متن انتخاب‌پذیر، "
    "در پنجره چاپ مقصد ذخیره PDF را انتخاب کنید.",
)
RECOVERY = (
    ("نشانه‌ها", "ذخیره با کد document_edit_conflict متوقف می‌شود و متن در ویرایشگر می‌ماند."),
    ("علت", "نسخه ذخیره‌شده پس از باز کردن ویرایشگر تغییر کرده است."),
    (
        "رفع مشکل",
        "متن ویرایش‌شده را کپی کنید، صفحه را تازه کنید "
        "و تغییرها را روی نسخه جدید اعمال و ذخیره کنید.",
    ),
    ("تأیید", "پس از ذخیره، صفحه را تازه کنید و متن نهایی را بررسی کنید."),
    ("پیشگیری", "پیش از شروع، صفحه را تازه کنید و از ویرایش هم‌زمان یک سند خودداری کنید."),
)


def upgrade() -> None:
    bind = op.get_bind()
    _update_export_help(OLD_PDF_DESCRIPTION, NEW_PDF_DESCRIPTION)
    bind.execute(
        sa.text(
            "INSERT INTO help_categories (slug, title, description) "
            "VALUES (:slug, :title, :description)"
        ),
        {"slug": CATEGORY, "title": "ویرایش و اشتراک اسناد", "description": "صورت‌جلسه و گزارش"},
    )
    statement = sa.text(
        "INSERT INTO help_articles (category_id, slug, title, summary, body_html, body_plain, "
        "kind, status, published_at) SELECT id, :slug, :title, :summary, :html, :plain, "
        ":kind, 'published', now() FROM help_categories WHERE slug = :category"
    )
    for slug, title, html, plain, kind in (
        (
            GUIDE,
            "ویرایش، چاپ و اشتراک صورت‌جلسه و گزارش",
            "<ol>" + "".join(f"<li>{escape(step)}</li>" for step in STEPS) + "</ol>",
            " ".join(STEPS),
            "article",
        ),
        (
            ERROR_SLUG,
            "تداخل ویرایش سند",
            "".join(f"<h2>{escape(title)}</h2><p>{escape(body)}</p>" for title, body in RECOVERY),
            " ".join(f"{title}: {body}" for title, body in RECOVERY),
            "error",
        ),
    ):
        bind.execute(
            statement,
            {
                "category": CATEGORY,
                "slug": slug,
                "title": title,
                "summary": title,
                "html": html,
                "plain": plain,
                "kind": kind,
            },
        )
    bind.execute(
        sa.text(
            "INSERT INTO help_error_codes "
            "(code, article_id, source, severity, title, quick_action) "
            "SELECT :code, id, 'api', 'warning', :title, :action "
            "FROM help_articles WHERE slug = :slug"
        ),
        {"code": ERROR, "slug": ERROR_SLUG, "title": "تداخل ویرایش سند", "action": RECOVERY[2][1]},
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM help_error_codes WHERE code = :code"), {"code": ERROR})
    bind.execute(
        sa.text("DELETE FROM help_articles WHERE slug IN (:guide, :error)"),
        {"guide": GUIDE, "error": ERROR_SLUG},
    )
    bind.execute(sa.text("DELETE FROM help_categories WHERE slug = :slug"), {"slug": CATEGORY})
    _update_export_help(NEW_PDF_DESCRIPTION, OLD_PDF_DESCRIPTION)


def _update_export_help(old: str, new: str) -> None:
    op.get_bind().execute(
        sa.text(
            "UPDATE help_articles SET body_html = replace(body_html, :old, :new), "
            "body_plain = replace(body_plain, :old, :new) "
            "WHERE slug = 'print-and-download-documents'"
        ),
        {"old": old, "new": new},
    )
