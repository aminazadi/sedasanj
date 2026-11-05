"""Help-center articles and error pages for speaker profiles (people and voiceprints)."""

# ruff: noqa: E501 - the article text is long Persian prose that does not wrap usefully

import html
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision = "0107_speaker_help_content"
down_revision = "0106_speaker_profiles"
branch_labels = None
depends_on = None

CATEGORY_SLUG = "meetings"

ARTICLES = [
    (
        "meetings-speaker-profiles",
        "افراد و ردصدا در جلسه‌نگار",
        "افرادی که در اپ تعریف می‌کنید با ردصدایشان روی صداسنج ذخیره می‌شوند و روی هر گوشی جفت‌شده برمی‌گردند.",
        [
            "در اپ جلسه‌نگار می‌توانید افراد را تعریف کنید و صدای هر نفر را با خواندن چند متن ثبت کنید. اپ از روی صدا فقط یک ردصدا (بردار عددی) می‌سازد و همان را به صداسنج می‌فرستد؛ فایل صدای ثبت‌نام به سرور نمی‌رود. ردصدا رمزشده نگه داشته می‌شود و هرگز در پنل یا خروجی نمایش داده نمی‌شود.",
            [
                "هر فرد به‌طور پیش‌فرض شخصی است و فقط خودتان آن را می‌بینید؛ اگر «اشتراک با سازمان» را روشن کنید، همکاران هم او را می‌بینند.",
                "پیش از ثبت صدا باید رضایت صریح همان فرد گرفته و در اپ تأیید شود.",
                "با جفت‌کردن گوشی جدید، افراد و ردصداها خودکار برمی‌گردند.",
                "حذف یک فرد، ردصدای او را از سرور و از دستگاه‌های دیگر هم پاک می‌کند.",
            ],
            "هر کاربر تا ۱۰۰ فرد و هر فرد تا ۲۴ نمونه ردصدا می‌تواند داشته باشد.",
        ],
    ),
]

# code, title, severity, cause, steps, quick action
ERRORS = [
    (
        "speaker_profile_not_found",
        "فرد پیدا نشد",
        "warning",
        "این فرد روی صداسنج وجود ندارد یا برای حساب شما قابل‌مشاهده نیست؛ ممکن است صاحبش آن را حذف کرده یا اشتراکش را برداشته باشد.",
        [
            "در اپ، فهرست افراد را تازه کنید (کشیدن به پایین).",
            "اگر فرد هنوز لازم است، او را دوباره تعریف و صدایش را ثبت کنید.",
        ],
        "فهرست افراد را در اپ تازه کنید.",
    ),
    (
        "speaker_profile_conflict",
        "تغییر هم‌زمان روی یک فرد",
        "warning",
        "همین فرد از دستگاه یا کاربر دیگری هم‌زمان تغییر کرده و نسخه‌ی شما قدیمی است.",
        [
            "اپ را چند ثانیه با اینترنت باز بگذارید تا همگام‌سازی تمام شود.",
            "تغییر خود را دوباره روی نسخه‌ی تازه انجام دهید.",
        ],
        "همگام‌سازی را اجرا کنید و تغییر را دوباره بزنید.",
    ),
    (
        "speaker_profile_limit",
        "به سقف تعداد افراد یا نمونه‌ها رسیده‌اید",
        "warning",
        "تعداد افراد شما به ۱۰۰ یا تعداد نمونه‌های ردصدای یک فرد به ۲۴ رسیده است.",
        [
            "افرادی را که دیگر لازم ندارید حذف کنید.",
            "برای یک فرد، نمونه‌های قدیمی یا کم‌کیفیت را پاک کنید.",
        ],
        "افراد یا نمونه‌های بی‌استفاده را حذف کنید.",
    ),
    (
        "speaker_consent_required",
        "رضایت فرد ثبت نشده است",
        "warning",
        "ردصدا بدون ثبت رضایت صریح فرد ذخیره نمی‌شود، چون صدا داده‌ی زیستی است.",
        ["در اپ، صفحه‌ی رضایت را برای این فرد بخوانید و تأیید کنید.", "سپس صدا را دوباره ثبت کنید."],
        "رضایت فرد را در اپ تأیید کنید.",
    ),
    (
        "speaker_voiceprint_invalid",
        "ردصدا نامعتبر است",
        "warning",
        "ردصدای ارسالی سالم نیست: طول یا قالب آن با مدل نمی‌خواند، مقدار ناصحیح دارد یا خالی است.",
        ["اپ را به آخرین نسخه به‌روز کنید.", "صدا را در محیط ساکن دوباره ثبت کنید."],
        "اپ را به‌روز کنید و صدا را دوباره ثبت کنید.",
    ),
    (
        "speaker_storage_unavailable",
        "ذخیره‌ی ردصدا موقتاً در دسترس نیست",
        "error",
        "کلید رمزنگاری ردصدا روی سرور تنظیم یا خوانده نشده است؛ تا برطرف شدن، ردصدا ذخیره یا بازیابی نمی‌شود. اطلاعات شما از بین نرفته است.",
        [
            "چند دقیقه بعد دوباره امتحان کنید؛ اپ خودش بازتلاش می‌کند.",
            "اگر ادامه داشت، مدیر سامانه باید مقدار VOICEPRINT_ENCRYPTION_KEY را در تنظیمات سرور بررسی کند.",
        ],
        "کمی بعد دوباره امتحان کنید یا به مدیر سامانه خبر دهید.",
    ),
]


def _slug(code: str) -> str:
    return "error-" + code.replace("_", "-")


def _body(blocks: Sequence[Sequence[str]]) -> tuple[str, str]:
    parts: list[str] = []
    plain: list[str] = []
    for block in blocks:
        if not isinstance(block, str):
            items = "".join(f"<li>{html.escape(step)}</li>" for step in block)
            parts.append(f"<ol>{items}</ol>")
            plain.extend(block)
        else:
            parts.append(f"<p>{html.escape(block)}</p>")
            plain.append(block)
    return "".join(parts), " ".join(plain)


def error_blocks(cause: str, steps: list[str], code: str) -> list[str | list[str]]:
    return [
        "علائم: ذخیره یا همگام‌سازی فرد یا ردصدا با خطا برگشت داده شد.",
        f"علت: {cause}",
        steps,
        "برای اطمینان، همان کار را دوباره انجام دهید؛ اگر باز هم خطا گرفتید با پشتیبانی تماس بگیرید و این کد را بگویید: "
        + code,
        "پیشگیری: اپ را به‌روز نگه دارید و پیش از ثبت صدا رضایت فرد را بگیرید.",
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
                "position": 30 + position,
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
                "position": 300 + position,
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
