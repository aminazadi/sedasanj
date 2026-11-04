"""Document account sign-in, password changes, and the new pairing location."""

from html import escape

import sqlalchemy as sa

from alembic import op

revision = "0103_account_access_help"
down_revision = "0102_organization_data"
branch_labels = None
depends_on = None

CATEGORY = "account-access"
GUIDE = "account-password-sign-in"
MEETING_ARTICLES = [
    "meetings-overview",
    "meetings-connect-app",
    "error-meeting-token-limit",
    "error-meeting-pairing-invalid",
]
ERRORS = {
    "login_mobile_ambiguous": (
        "شماره موبایل برای چند حساب مشترک است",
        "این شماره و گذرواژه برای چند حساب یکسان است. "
        "در تب «گذرواژه» ایمیل حساب موردنظر را وارد کنید.",
    ),
    "password_change_mobile_required": (
        "شماره موبایل معتبر برای تغییر گذرواژه لازم است",
        "شماره موبایل را در اطلاعات فردی پروفایل ثبت کنید. "
        "پس از ذخیره، دوباره درخواست ارسال کد بدهید.",
    ),
    "password_change_verification_required": (
        "تأیید پیامکی برای تغییر گذرواژه لازم است",
        "کد قبلی مصرف شده، منقضی شده یا مربوط به شمارهٔ دیگری است. "
        "از بخش «تغییر گذرواژه» در پروفایل، کد جدید بگیرید.",
    ),
    "password_change_totp_required": (
        "کد ورود دومرحله‌ای لازم است",
        "کد فعلی صداسنج را از برنامهٔ احراز هویت خود وارد کنید. "
        "اگر زمان کد گذشته است، از کد تازه استفاده کنید.",
    ),
}


def _update_pairing_location(old: str, new: str) -> None:
    op.get_bind().execute(
        sa.text(
            "UPDATE help_articles SET body_html = replace(body_html, :old, :new), "
            "body_plain = replace(body_plain, :old, :new) WHERE slug = ANY(:slugs)"
        ),
        {"old": old, "new": new, "slugs": MEETING_ARTICLES},
    )


def upgrade() -> None:
    _update_pairing_location("«پروفایل»", "«تنظیمات حساب ← اتصال‌ها»")
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "INSERT INTO help_categories (slug, title, description) VALUES "
            "(:slug, 'ورود و امنیت حساب', 'ورود با شماره موبایل یا ایمیل و تغییر گذرواژه')"
        ),
        {"slug": CATEGORY},
    )
    article = sa.text(
        "INSERT INTO help_articles (category_id, slug, title, summary, body_html, "
        "body_plain, kind, status, published_at) "
        "SELECT id, :slug, :title, :summary, :html, :plain, :kind, 'published', now() "
        "FROM help_categories WHERE slug = :category"
    )
    steps = [
        "در صفحه ورود، تب «گذرواژه» را انتخاب کنید و ایمیل یا شمارهٔ موبایل ثبت‌شده "
        "را همراه گذرواژه وارد کنید. اگر شماره بین چند حساب مشترک است و گذرواژه‌ها "
        "یکسان‌اند، از ایمیل حساب موردنظر استفاده کنید.",
        "برای تغییر گذرواژه، وارد حساب شوید و در «پروفایل من» به بخش «تغییر گذرواژه» بروید.",
        "کد پیامکی را به شمارهٔ ثبت‌شده بفرستید. کد شش‌رقمی، گذرواژهٔ جدید و تکرار آن "
        "را وارد کنید. اگر ورود دومرحله‌ای فعال است، کد برنامهٔ احراز هویت را هم وارد کنید.",
        "پس از دیدن پیام موفقیت، برای ورود بعدی از گذرواژهٔ جدید استفاده کنید.",
    ]
    bind.execute(
        article,
        {
            "category": CATEGORY,
            "slug": GUIDE,
            "title": "ورود و تغییر گذرواژه",
            "summary": "ورود با ایمیل یا شماره موبایل و تغییر گذرواژه با کد پیامکی",
            "html": "<ol>" + "".join(f"<li>{escape(step)}</li>" for step in steps) + "</ol>",
            "plain": " ".join(steps),
            "kind": "article",
        },
    )
    for code, (title, action) in ERRORS.items():
        slug = "error-" + code.replace("_", "-")
        bind.execute(
            article,
            {
                "category": CATEGORY,
                "slug": slug,
                "title": title,
                "summary": action,
                "html": f"<p>{escape(action)}</p>",
                "plain": action,
                "kind": "error",
            },
        )
        bind.execute(
            sa.text(
                "INSERT INTO help_error_codes (code, article_id, source, severity, title, "
                "quick_action) SELECT :code, id, 'api', 'warning', :title, :action "
                "FROM help_articles WHERE slug = :slug"
            ),
            {"code": code, "slug": slug, "title": title, "action": action},
        )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text("DELETE FROM help_error_codes WHERE code = ANY(:codes)"), {"codes": list(ERRORS)}
    )
    bind.execute(
        sa.text("DELETE FROM help_articles WHERE slug = ANY(:slugs)"),
        {"slugs": [GUIDE, *("error-" + code.replace("_", "-") for code in ERRORS)]},
    )
    bind.execute(sa.text("DELETE FROM help_categories WHERE slug = :slug"), {"slug": CATEGORY})
    _update_pairing_location("«تنظیمات حساب ← اتصال‌ها»", "«پروفایل»")
