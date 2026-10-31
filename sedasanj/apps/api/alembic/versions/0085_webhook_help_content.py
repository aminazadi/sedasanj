"""Help-center article for webhooks: events, signature check, retries, rotation and the delivery log."""

# ruff: noqa: E501 - the article text is long Persian prose that does not wrap usefully

import html

import sqlalchemy as sa

from alembic import op

revision = "0085_webhook_help_content"
down_revision = "0084_webhook_management"
branch_labels = None
depends_on = None

CATEGORY = ("api-integration", "اتصال API", "کلید API، دسترسی‌ها و اتصال سیستم‌های بیرونی")

ARTICLES = [
    (
        "webhooks-guide",
        "وب‌هوک: رویدادها، امضا و تلاش مجدد",
        "نتیجه تحلیل تماس به آدرس شما فرستاده می‌شود؛ امضا را بررسی کنید و با شناسه تحویل تکراری‌ها را حذف کنید.",
        [
            "رویدادها: call.complete (تحلیل کامل شد)، call.failed، sales.insight و balance.low. فهرست کامل و شکل پیام در GET /v1/webhooks/events است. دکمهٔ «تست» رویداد webhook.ping را برای آزمایش اتصال می‌فرستد.",
            "هر درخواست این هدرها را دارد: X-CBI-Event، X-CBI-Delivery (شناسهٔ ثابت هر تحویل، حتی در تلاش مجدد)، X-CBI-Attempt، X-CBI-Timestamp و X-CBI-Signature.",
            [
                "بدنهٔ خام درخواست را بخوانید و تغییرش ندهید.",
                "مقدار timestamp + نقطه + بدنهٔ خام را با HMAC-SHA256 و کلید امضای وب‌هوک امضا کنید.",
                "پیشوند sha256= را به ابتدای نتیجه بگذارید و با X-CBI-Signature به‌صورت زمان‌ثابت مقایسه کنید.",
                "اگر timestamp از ۵ دقیقه قدیمی‌تر بود درخواست را رد کنید.",
                "اگر X-CBI-Delivery را قبلاً پردازش کرده‌اید، فقط پاسخ ۲۰۰ بدهید و دوباره پردازش نکنید.",
            ],
            "پاسخ ۲xx یعنی موفق. در صورت شکست، تلاش مجدد با فاصلهٔ افزایشی تا ۸ بار انجام می‌شود و فقط برای وب‌هوکی که جواب نداده تکرار می‌شود. بعد از ۱۰ شکست پیاپی وب‌هوک غیرفعال و به مدیران ایمیل می‌شود؛ پس از رفع مشکل دوباره فعالش کنید.",
            "چرخش کلید: بعد از «چرخش کلید» کلید جدید فقط یک بار نمایش داده می‌شود و تا ۲۴ ساعت هر درخواست یک امضای دوم با کلید قبلی در X-CBI-Signature-Previous دارد تا بدون قطعی کلید را عوض کنید.",
            "لاگ تحویل ۳۰ روز نگهداری می‌شود. از آن می‌توانید وضعیت، تأخیر و علت شکست هر تلاش را ببینید و تحویل را دوباره بفرستید.",
        ],
    ),
]

ERRORS: list = []


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
        "علائم: درخواست API با خطا برگشت داده شد.",
        f"علت: {cause}",
        steps,
        "برای اطمینان، همان درخواست را دوباره بفرستید؛ اگر باز هم خطا گرفتید با پشتیبانی تماس بگیرید و این کد را بگویید: "
        + code,
        "پیشگیری: شناسه تماس را از شمارنده یا شناسه یکتای مرکز تلفن بسازید.",
    ]


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "INSERT INTO help_categories (slug, title, description, position) "
            "VALUES (:slug, :title, :description, 60) ON CONFLICT (slug) DO NOTHING"
        ),
        {"slug": CATEGORY[0], "title": CATEGORY[1], "description": CATEGORY[2]},
    )
    category_id = bind.execute(
        sa.text("SELECT id FROM help_categories WHERE slug = :slug"), {"slug": CATEGORY[0]}
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
                "position": position,
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
                "position": 100 + position,
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
    bind.execute(
        sa.text(
            "DELETE FROM help_categories WHERE slug = :slug AND NOT EXISTS "
            "(SELECT 1 FROM help_articles WHERE category_id = help_categories.id)"
        ),
        {"slug": CATEGORY[0]},
    )
