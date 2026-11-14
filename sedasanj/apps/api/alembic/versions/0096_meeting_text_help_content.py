"""Help-center articles and error pages for text-only meetings and custom AI instructions."""

# ruff: noqa: E501 - the article text is long Persian prose that does not wrap usefully

import html

import sqlalchemy as sa

from alembic import op

revision = "0096_meeting_text_help_content"
down_revision = "0095_meeting_text_ingest"
branch_labels = None
depends_on = None

CATEGORY_SLUG = "meetings"

ARTICLES = [
    (
        "meetings-send-transcript",
        "ارسال متن جلسه از اپ",
        "اپ جلسه‌نگار متن جلسه و فایل صدا را می‌فرستد؛ صورت‌جلسه فقط از روی متن ساخته می‌شود و صدا رونویسی نمی‌شود.",
        [
            "متن جلسه هنگام ضبط روی گوشی ساخته می‌شود. پس از پایان ضبط، اگر سوییچ «ارسال متن جلسه» در تنظیمات اپ روشن باشد، همان متن به صداسنج فرستاده و صورت‌جلسه ساخته می‌شود. صدای جلسه هم به‌صورت تکه‌تکه فرستاده و در صفحه جلسه برای پخش نگه داشته می‌شود؛ صداسنج آن را به متن تبدیل نمی‌کند.",
            [
                "در اپ، تنظیمات را باز کنید و سوییچ «ارسال متن جلسه» را روشن بگذارید.",
                "مدل شنوا و متن زنده را در اپ فعال نگه دارید؛ بدون متن، چیزی برای ارسال وجود ندارد.",
                "اگر جلسه‌ای ارسال نشد، در جزئیات آن «ارسال متن این جلسه» را بزنید.",
            ],
            "هزینه جلسه بر اساس مدت جلسه از اعتبار سازمان کم می‌شود. فایل صدا طبق مدت نگهداری صدای سازمان حذف می‌شود؛ متن و صورت‌جلسه می‌ماند.",
        ],
    ),
    (
        "meetings-custom-instructions",
        "دستورهای سفارشی هوش مصنوعی",
        "مدیر سازمان می‌تواند برای صورت‌جلسه و بازخورد مربی دستور تکمیلی بنویسد.",
        [
            "دستور سازمان به پرامپت پایه اضافه می‌شود و جایگزین آن نمی‌شود؛ قالب خروجی همیشه ثابت می‌ماند.",
            [
                "در پنل سازمان، بخش «دستورهای سفارشی هوش مصنوعی» را باز کنید.",
                "برای جلسات یا مربی، لحن، اصطلاحات و ساختار دلخواه را بنویسید (حداکثر ۸٬۰۰۰ نویسه).",
                "ذخیره کنید؛ از جلسه یا تماس بعدی اعمال می‌شود.",
            ],
            "برای ساخت دوباره‌ی یک صورت‌جلسه با دستور جدید، در جزئیات جلسه «بازتحلیل» را بزنید.",
        ],
    ),
]

# code, title, severity, cause, steps, quick action
ERRORS = [
    (
        "meeting_transcript_missing",
        "متن جلسه رسیده نیست",
        "warning",
        "پایان جلسه زده شد ولی متنی برای آن دریافت نشده بود.",
        [
            "در اپ مطمئن شوید متن زنده روشن و مدل شنوا نصب است.",
            "در جزئیات جلسه «ارسال متن این جلسه» را بزنید.",
        ],
        "متن جلسه را دوباره بفرستید.",
    ),
    (
        "meeting_transcript_invalid",
        "متن جلسه نامعتبر است",
        "warning",
        "ساختار یا اندازه متن ارسالی با قواعد صداسنج نمی‌خواند.",
        [
            "اپ را به آخرین نسخه به‌روز کنید.",
            "اگر جلسه بسیار طولانی است، آن را در چند جلسه ضبط کنید.",
        ],
        "اپ را به‌روز کنید.",
    ),
    (
        "tenant_instructions_too_long",
        "دستور سفارشی بیش از حد طولانی است",
        "warning",
        "متن دستور سفارشی از ۸٬۰۰۰ نویسه بیشتر است.",
        ["متن را کوتاه کنید.", "فقط قواعد مهم را نگه دارید و دوباره ذخیره کنید."],
        "متن را کوتاه کنید.",
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
        "علائم: درخواست یا پردازش جلسه با خطا برگشت داده شد.",
        f"علت: {cause}",
        steps,
        "برای اطمینان، همان کار را دوباره انجام دهید؛ اگر باز هم خطا گرفتید با پشتیبانی تماس بگیرید و این کد را بگویید: "
        + code,
        "پیشگیری: اپ را به‌روز نگه دارید و پیش از جلسه‌های طولانی اعتبار حساب را بررسی کنید.",
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
                "position": 10 + position,
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
                "position": 200 + position,
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
