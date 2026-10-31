"""Help-center article for the integration read API, and the conflict_idempotency error page."""

# ruff: noqa: E501 - the article text is long Persian prose that does not wrap usefully

import html

import sqlalchemy as sa

from alembic import op

revision = "0083_integration_api_help_content"
down_revision = "0082_audio_levels_help_content"
branch_labels = None
depends_on = None

CATEGORY = ("api-integration", "اتصال API", "کلید API، دسترسی‌ها و اتصال سیستم‌های بیرونی")

ARTICLES = [
    (
        "crm-integration-api",
        "اتصال CRM با API صداسنج",
        "خواندن نتایج تماس، جست‌وجوی مخاطب با شماره و ثبت نتیجه فروش از CRM با کلید API.",
        [
            "برای خواندن نتایج، کلید API با دسترسی «خواندن تماس‌ها و نتایج تحلیل» (calls:read) بسازید. برای جست‌وجوی مخاطب دسترسی contacts:read و برای ثبت نتیجه فروش دسترسی crm:write لازم است.",
            "هنگام ارسال تماس، مقدار external_reference را شناسه همان تماس یا سرنخ در CRM خودتان بگذارید تا بعداً بتوانید با آن تماس را پیدا کنید.",
            [
                "تماس را با GET /v1/integration/calls/by-external/{شناسه} پیدا کنید.",
                "فهرست تماس‌ها را با GET /v1/integration/calls و پارامترهای from، to، number و campaign_id بخوانید و با next_cursor صفحه بعد را بگیرید.",
                "مخاطب و آخرین تماس‌های یک شماره را با GET /v1/integration/contacts/lookup?phone=09120000000 بگیرید.",
                "نتیجه فروش را با POST /v1/crm/outcomes ثبت کنید؛ برای ارسال گروهی تا ۵۰۰ مورد از /v1/crm/outcomes/bulk استفاده کنید.",
            ],
            "ثبت نتیجه برای هر external_lead_id تکرارپذیر است: ارسال دوباره امن است و مقدار قدیمی‌تر روی جدیدتر نمی‌نشیند. با strict_match=true اگر تماس پیدا نشود خطا می‌گیرید.",
            "فیلد metadata تا ۲۰ کلید ساده (متن، عدد یا بله/خیر) را نگه می‌دارد و همان را در فهرست نتایج پس می‌گیرید.",
            "این API هیچ دسترسی به دستیار هوشمند ندارد؛ دستیار فقط از داخل پنل صداسنج در دسترس است.",
        ],
    ),
]

ERRORS = [
    (
        "conflict_idempotency",
        "این شناسه تماس قبلاً با اطلاعات دیگری ثبت شده",
        "warning",
        "همان asterisk_uniqueid همراه با Idempotency-Key و با شماره مبدأ یا مقصد متفاوت ارسال شده است.",
        [
            "بررسی کنید که شناسه تماس برای هر تماس یکتا باشد.",
            "اگر این تماس جدید است، شناسه جدید بفرستید.",
            "اگر ارسال مجدد همان تماس است، همان شماره‌ها را بفرستید تا تماس اولیه برگردد.",
        ],
        "برای تماس جدید شناسه یکتای تازه بفرستید.",
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
