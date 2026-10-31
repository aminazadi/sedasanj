"""Help-center article and error pages for API key scopes, expiry and address limits."""

# ruff: noqa: E501 - the article text is long Persian prose that does not wrap usefully

import html

import sqlalchemy as sa

from alembic import op

revision = "0081_api_key_help_content"
down_revision = "0080_api_key_scopes"
branch_labels = None
depends_on = None

CATEGORY = ("api-integration", "اتصال API", "کلید API، دسترسی‌ها و اتصال سیستم‌های بیرونی")

ARTICLES = [
    (
        "api-keys-and-scopes",
        "کلید API و دسترسی‌ها",
        "هر کلید فقط کارهایی را انجام می‌دهد که برایش فعال کرده‌اید؛ هیچ کلیدی به دستیار هوشمند دسترسی ندارد.",
        [
            "هر کلید API سه نوع دسترسی دارد: «ارسال تماس و داخلی‌ها» (ingest:write)، «به‌روزرسانی و گزارش ماژول مرکز تلفن» (module:sync) و «ثبت نتیجه CRM» (crm:write). کلید جدید به‌صورت پیش‌فرض فقط دسترسی ارسال تماس و ماژول را دارد.",
            "برای محدودکردن ریسک، می‌توانید تاریخ انقضا بگذارید یا فقط چند IP را مجاز کنید. درخواست از آدرس دیگر رد می‌شود.",
            [
                "از «حساب» بخش کلیدهای API را باز کنید.",
                "برای کلید موجود «ویرایش» را بزنید و دسترسی‌ها، انقضا و IPهای مجاز را تنظیم کنید.",
                "برای تعویض امن کلید «چرخش کلید» را بزنید؛ کلید جدید ساخته می‌شود و کلید قبلی تا ۲۴ ساعت معتبر می‌ماند.",
                "تنظیم مرکز تلفن را با کلید جدید به‌روز کنید و سپس کلید قبلی را لغو کنید.",
            ],
            "دستیار هوشمند فقط از داخل پنل صداسنج با ورود کاربر در دسترس است و با هیچ کلید API قابل استفاده نیست.",
        ],
    ),
]

ERRORS = [
    (
        "api_key_scope_denied",
        "کلید این دسترسی را ندارد",
        "warning",
        "کلیدی که استفاده کرده‌اید برای این عملیات فعال نشده است.",
        [
            "در بخش کلیدهای API، کلید را ویرایش کنید.",
            "دسترسی مورد نیاز (مثلاً «ثبت نتیجه CRM») را فعال و ذخیره کنید.",
            "درخواست را دوباره بفرستید.",
        ],
        "دسترسی لازم را در ویرایش کلید فعال کنید.",
    ),
    (
        "api_key_expired",
        "کلید API منقضی شده است",
        "warning",
        "تاریخ انقضای کلید گذشته است.",
        [
            "در بخش کلیدهای API تاریخ انقضا را تمدید کنید یا کلید جدید بسازید.",
            "تنظیم مرکز تلفن یا سیستم خود را با کلید جدید به‌روز کنید.",
        ],
        "انقضای کلید را تمدید کنید یا کلید جدید بسازید.",
    ),
    (
        "ip_not_allowed",
        "آدرس درخواست‌دهنده مجاز نیست",
        "warning",
        "کلید فقط از IPهای مشخص‌شده قابل استفاده است و درخواست از آدرس دیگری رسیده است.",
        [
            "آدرس خروجی سرور خود را بررسی کنید.",
            "آن آدرس را در «IPهای مجاز» کلید اضافه کنید یا فهرست را خالی بگذارید.",
        ],
        "IP سرور را به فهرست مجاز کلید اضافه کنید.",
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
        "پیشگیری: انقضا و IPهای مجاز کلیدها را گاهی در «حساب» بررسی کنید.",
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
