"""Help for linking a Jalase-Negar account to a SedaSanj organization and the panel menu."""

# ruff: noqa: E501 - Persian help prose is kept in complete paragraphs.

import sqlalchemy as sa

from alembic import op

revision = "0155_jalase_links_help"
down_revision = "0154_jalase_account_links"
branch_labels = None
depends_on = None

SLUG = "jalase-negar-link-organization"
TITLE = "اتصال جلسه‌نگار شخصی به سازمان صداسنج"
SUMMARY = "اتصال حساب شخصی جلسه‌نگار به سازمان با کد جفت‌سازی، قطع اتصال و منوی اسناد در پنل."
BODY = (
    "<h2>اتصال چگونه کار می‌کند</h2><p>مدیر سازمان در پنل صداسنج کد جفت‌سازی می‌سازد. در اپ، بخش «اتصال به سازمان» را باز کنید و کد را وارد کنید. اپ یک کلید جداگانهٔ سازمانی می‌گیرد و حساب شخصی شما دست‌نخورده می‌ماند؛ در هر ارسال انتخاب می‌کنید جلسه شخصی باشد یا سازمانی. جلسهٔ سازمانی از اشتراک سازمان حساب می‌شود و جلسهٔ شخصی از ساعت‌های خودتان. هیچ داده‌ای به‌صورت خودکار بین دو فضا جابه‌جا نمی‌شود.</p>"
    "<h2>منوی پنل</h2><p>هر دستهٔ سند (مثلاً جلسات مشاوره) با اولین سندش در منوی پنل سازمان ظاهر می‌شود. مدیر سازمان می‌تواند هر دسته را پنهان یا دوباره نمایان کند.</p>"
    '<h2>خطاها</h2><p><code dir="ltr">link_invalid_target</code>: کد مربوط به سازمان صداسنج نیست. <code dir="ltr">link_already_exists</code>: حساب شما همین حالا به این سازمان وصل است. <code dir="ltr">link_not_found</code>: اتصال پیدا نشد یا قبلاً قطع شده است.</p>'
    "<h2>رفع مشکل</h2><ol><li>کد جفت‌سازی تازه از پنل سازمان بگیرید؛ هر کد یک بار و کوتاه‌مدت معتبر است.</li>"
    "<li>برای اتصال دوباره، ابتدا اتصال قبلی را در اپ قطع کنید.</li>"
    "<li>اگر کد را از حساب شخصی گرفته‌اید، باید از پنل یک سازمان صداسنج بگیرید.</li></ol>"
    "<h2>قطع اتصال</h2><p>با قطع اتصال، کلید سازمانی باطل می‌شود؛ جلسه‌ها و اسناد سازمان در سازمان می‌مانند و اسناد شخصی شما در حساب شخصی.</p>"
    "<h2>تأیید رفع مشکل</h2><p>پس از اتصال، نام سازمان در فهرست اتصال‌های اپ دیده می‌شود.</p>"
)
CODES = (
    (
        "link_invalid_target",
        "این کد مربوط به سازمان صداسنج نیست.",
        "کد را از پنل سازمان صداسنج بگیرید.",
    ),
    (
        "link_already_exists",
        "حساب شما به این سازمان وصل است.",
        "اتصال قبلی را قطع و دوباره وصل شوید.",
    ),
    ("link_not_found", "اتصال پیدا نشد یا قبلاً قطع شده است.", "فهرست اتصال‌ها را تازه کنید."),
)


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "INSERT INTO help_articles (slug,title,summary,body_html,body_plain,kind,status,"
            "position,published_at) "
            "VALUES (:slug,:title,:summary,:body,:summary,'article','published',156,now()) "
            "ON CONFLICT (slug) DO NOTHING"
        ),
        {"slug": SLUG, "title": TITLE, "summary": SUMMARY, "body": BODY},
    )
    for code, summary, action in CODES:
        bind.execute(
            sa.text(
                "INSERT INTO help_error_codes (code,source,severity,article_id,title,quick_action) "
                "SELECT :code,'api','error',id,:summary,:action "
                "FROM help_articles WHERE slug=:slug ON CONFLICT (code) DO NOTHING"
            ),
            {"slug": SLUG, "code": code, "summary": summary, "action": action},
        )


def downgrade() -> None:
    bind = op.get_bind()
    for code, _summary, _action in CODES:
        bind.execute(sa.text("DELETE FROM help_error_codes WHERE code=:code"), {"code": code})
    bind.execute(sa.text("DELETE FROM help_articles WHERE slug=:slug"), {"slug": SLUG})
