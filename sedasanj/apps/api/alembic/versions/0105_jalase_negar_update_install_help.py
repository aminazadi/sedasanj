"""Help-center error pages for the app's automatic update (checksum, downgrade, blocked install)."""

# ruff: noqa: E501 - the article text is long Persian prose that does not wrap usefully

import html

import sqlalchemy as sa

from alembic import op

revision = "0105_jalase_negar_update_install_help"
down_revision = "0104_jalase_negar_release_rollout"
branch_labels = None
depends_on = None

CATEGORY_SLUG = "meetings"

ARTICLES = [
    (
        "meetings-app-auto-update",
        "به‌روزرسانی خودکار جلسه‌نگار",
        "اپ خودش نسخه‌ی جدید را در لحظه‌ی آرام دانلود و نصب می‌کند؛ اگر اندروید اجازه ندهد، یک اعلان یک‌لمسی می‌بینید.",
        [
            "جلسه‌نگار هر چند ساعت یک‌بار در پس‌زمینه نسخه‌ی جدید را بررسی می‌کند و فقط روی شبکه‌ی وای‌فای و وقتی باتری کافی است دانلود می‌کند. فایل پیش از نصب با اثر انگشت اعلام‌شده، شماره‌ی نسخه و امضای سازنده بررسی می‌شود.",
            [
                "نصب فقط وقتی انجام می‌شود که ضبط فعال نیست، همه‌ی ارسال‌ها تمام شده‌اند و اپ در پس‌زمینه است؛ هرگز وسط جلسه نصب نمی‌شود.",
                "یک‌بار باید در تنظیمات اندروید برای جلسه‌نگار گزینه‌ی «نصب برنامه‌های ناشناس» را روشن کنید. اگر روشن نکنید، همه‌چیز مثل قبل می‌ماند و می‌توانید نسخه را دستی دریافت کنید.",
                "در بعضی گوشی‌ها اندروید هنوز یک پنجره‌ی تأیید نشان می‌دهد؛ در این حالت اعلان «نسخه‌ی جدید آماده است» می‌آید و با یک لمس نصب می‌شود.",
                "اپ هیچ اطلاعات شخصی نمی‌فرستد؛ فقط یک شناسه‌ی تصادفی نصب برای انتشار مرحله‌ای و نتیجه‌ی نصب (موفق یا کد خطا).",
            ],
            "اگر به‌روزرسانی خودکار نمی‌خواهید، مجوز نصب را روشن نکنید یا آن را در تنظیمات اندروید خاموش کنید.",
        ],
    ),
]

# code, title, severity, symptom, cause, steps, quick action
ERRORS = [
    (
        "update_checksum_mismatch",
        "فایل به‌روزرسانی سالم نیست",
        "warning",
        "فایل دانلودشده با اثر انگشت (SHA-256) اعلام‌شده توسط صداسنج نمی‌خواند؛ دانلود ناقص یا دست‌کاری‌شده بوده و نصب نشد.",
        [
            "اپ فایل ناقص را پاک می‌کند و در بررسی بعدی دوباره دانلود می‌کند.",
            "اگر دوباره تکرار شد، با اینترنت دیگری امتحان کنید یا نسخه را از صفحه‌ی دریافت اپ دستی نصب کنید.",
        ],
        "کمی بعد دوباره امتحان کنید یا نسخه را دستی دریافت کنید.",
    ),
    (
        "update_downgrade_rejected",
        "نسخه‌ی پیشنهادی قدیمی‌تر از نسخه‌ی نصب‌شده است",
        "warning",
        "نسخه‌ی دانلودشده شماره‌ی ساخت بالاتری از نسخه‌ی فعلی ندارد یا با امضای اپ نصب‌شده نمی‌خواند، پس برای ایمنی نصب نشد.",
        [
            "نیازی به اقدام نیست؛ اپ فعلی دست‌نخورده می‌ماند.",
            "اگر پیام تکرار شد، اپ را از صفحه‌ی رسمی دریافت جلسه‌نگار دوباره نصب کنید و به پشتیبانی خبر دهید.",
        ],
        "اپ فعلی سالم است؛ در صورت تکرار به پشتیبانی خبر دهید.",
    ),
    (
        "update_install_blocked",
        "اندروید نصب خودکار را مسدود کرد",
        "warning",
        "اندروید یا سازنده‌ی گوشی اجازه‌ی نصب بی‌صدا نداد، مجوز «نصب برنامه‌های ناشناس» روشن نیست یا حافظه کافی نیست.",
        [
            "روی اعلان «نسخه‌ی جدید آماده است» بزنید و نصب را تأیید کنید.",
            "برای نصب خودکار در آینده، در تنظیمات اندروید برای جلسه‌نگار «نصب برنامه‌های ناشناس» را روشن کنید.",
            "اگر حافظه‌ی گوشی پر است، فایل‌های بی‌استفاده را پاک کنید.",
        ],
        "اعلان به‌روزرسانی را لمس کنید.",
    ),
]


def _slug(code: str) -> str:
    return "error-" + code.replace("_", "-")


def _body(blocks: list) -> tuple[str, str]:
    parts: list[str] = []
    plain: list[str] = []
    for block in blocks:
        if isinstance(block, list):
            items = "".join(f"<li>{html.escape(step)}</li>" for step in block)
            parts.append(f"<ol>{items}</ol>")
            plain.extend(block)
        else:
            parts.append(f"<p>{html.escape(block)}</p>")
            plain.append(block)
    return "".join(parts), " ".join(plain)


def error_blocks(cause: str, steps: list[str], code: str) -> list:
    return [
        "علائم: به‌روزرسانی خودکار جلسه‌نگار انجام نشد.",
        f"علت: {cause}",
        steps,
        "اگر باز هم خطا گرفتید با پشتیبانی تماس بگیرید و این کد را بگویید: " + code,
        "پیشگیری: اپ را روی شبکه‌ی پایدار و با باتری کافی در پس‌زمینه بگذارید.",
    ]


def upgrade() -> None:
    bind = op.get_bind()
    category_id = bind.execute(
        sa.text("SELECT id FROM help_categories WHERE slug = :slug"), {"slug": CATEGORY_SLUG}
    ).scalar_one()
    insert_article = sa.text(
        "INSERT INTO help_articles (slug, category_id, title, summary, body_html, body_plain, "
        "kind, status, position, published_at) "
        "VALUES (:slug, :category, :title, :summary, :html, :plain, :kind, 'published', :position, now()) "
        "ON CONFLICT (slug) DO NOTHING"
    )
    for position, (slug, title, summary, blocks) in enumerate(ARTICLES):
        body_html, body_plain = _body(blocks)
        bind.execute(
            insert_article,
            {
                "slug": slug,
                "category": category_id,
                "title": title,
                "summary": summary,
                "html": body_html,
                "plain": body_plain,
                "kind": "article",
                "position": 40 + position,
            },
        )
    for position, (code, title, severity, cause, steps, quick) in enumerate(ERRORS):
        body_html, body_plain = _body(error_blocks(cause, steps, code))
        bind.execute(
            insert_article,
            {
                "slug": _slug(code),
                "category": category_id,
                "title": title,
                "summary": cause,
                "html": body_html,
                "plain": body_plain,
                "kind": "error",
                "position": 400 + position,
            },
        )
        bind.execute(
            sa.text(
                "INSERT INTO help_error_codes (code, article_id, source, severity, title, quick_action) "
                "SELECT :code, id, 'api', :severity, :title, :quick FROM help_articles WHERE slug = :slug "
                "ON CONFLICT (code) DO NOTHING"
            ),
            {
                "code": code,
                "severity": severity,
                "title": title,
                "quick": quick,
                "slug": _slug(code),
            },
        )


def downgrade() -> None:
    bind = op.get_bind()
    codes = [code for code, *_ in ERRORS]
    bind.execute(sa.text("DELETE FROM help_error_codes WHERE code = ANY(:codes)"), {"codes": codes})
    slugs = [slug for slug, *_ in ARTICLES] + [_slug(code) for code in codes]
    bind.execute(sa.text("DELETE FROM help_articles WHERE slug = ANY(:slugs)"), {"slugs": slugs})
