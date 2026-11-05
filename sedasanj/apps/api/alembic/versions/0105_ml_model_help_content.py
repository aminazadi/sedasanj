"""Help-center articles and error pages for the ML model registry (staff and publisher)."""

# ruff: noqa: E501 - the article text is long Persian prose that does not wrap usefully

import html

import sqlalchemy as sa

from alembic import op

revision = "0105_ml_model_help_content"
down_revision = "0104_ml_model_releases"
branch_labels = None
depends_on = None

CATEGORY_SLUG = "meetings"

ARTICLES = [
    (
        "ml-model-registry",
        "مخزن مدل‌های یادگیری ماشین",
        "مدل‌های آموزش‌دیده روی GPU در MinIO ذخیره می‌شوند و کارکنان از پنل مدیریت آن‌ها را دانلود می‌کنند.",
        [
            "هر مدل جدید پس از پایان آموزش با کلید ناشر (دامنه‌ی ml:publish) به صداسنج آپلود می‌شود. سرور خودش SHA-256 فایل را حساب و با مقدار اعلام‌شده مقایسه می‌کند و فقط در صورت تطابق مدل را «آماده» می‌کند.",
            [
                "کانال latest همیشه فقط یک نسخه نگه می‌دارد: با آماده‌شدن نسخه‌ی تازه، فایل نسخه‌ی قبلی از MinIO پاک می‌شود و فقط سطر آن به‌عنوان سابقه می‌ماند.",
                "کانال champion نسخه‌ی قبلی را تا ml_model_prev_retention_hours ساعت (پیش‌فرض ۷۲) نگه می‌دارد، مگر پین شده باشد.",
                "دانلود برای همه‌ی کارکنان ممکن است و هر بار در گزارش رویدادها ثبت می‌شود؛ ارتقا، درصد انتشار، ابطال، حذف و پین فقط برای مدیر ارشد و با تأیید رمز است.",
            ],
            "پس از دانلود، SHA-256 فایل را با مقدار نمایش‌داده‌شده در پنل مقایسه کنید.",
        ],
    ),
]

# code, title, severity, cause, steps, quick action
ERRORS = [
    (
        "ml_model_not_found",
        "مدل پیدا نشد",
        "warning",
        "این نسخه‌ی مدل در مخزن وجود ندارد یا فایل آن به‌دلیل جایگزینی با نسخه‌ی جدیدتر پاک شده است.",
        [
            "فهرست مدل‌ها را در پنل تازه کنید.",
            "اگر نسخه‌ی قدیمی لازم است، آموزش یا آپلود آن را دوباره انجام دهید.",
        ],
        "فهرست مدل‌ها را تازه کنید.",
    ),
    (
        "ml_model_checksum_mismatch",
        "SHA-256 فایل با مقدار اعلام‌شده نمی‌خواند",
        "error",
        "فایل در مسیر آپلود خراب شده یا مقدار sha256 ارسالی برای فایل دیگری است؛ مدل ذخیره نشد.",
        [
            "SHA-256 فایل ONNX را دوباره حساب کنید (sha256sum model.onnx).",
            "با همان فایل و مقدار درست دوباره آپلود کنید.",
        ],
        "هش را دوباره حساب کنید و آپلود را تکرار کنید.",
    ),
    (
        "ml_model_invalid",
        "فایل یا مشخصات مدل نامعتبر است",
        "error",
        "فایل خالی یا بزرگ‌تر از سقف مجاز است، قالب ONNX ندارد، یا kind، version، کانال یا متادیتا درست نیست.",
        [
            "پیام خطا را بخوانید؛ فیلد مشکل‌دار در آن آمده است.",
            "فایل را دوباره از خروجی آموزش بسازید و با ml/speaker/publish.py بفرستید.",
        ],
        "مشخصات را اصلاح کنید و دوباره آپلود کنید.",
    ),
    (
        "ml_model_version_conflict",
        "این نسخه قبلاً با محتوای دیگری ثبت شده است",
        "warning",
        "برای همین kind و version مدلی با SHA-256 متفاوت وجود دارد؛ نسخه‌ی ثبت‌شده تغییر نمی‌کند.",
        [
            "شماره‌ی نسخه‌ی مدل جدید را افزایش دهید.",
            "اگر همان فایل را دوباره می‌فرستید، آپلود بی‌خطر و بدون اثر اضافه است.",
        ],
        "نسخه‌ی تازه‌ای برای این مدل بسازید.",
    ),
    (
        "ml_publish_forbidden",
        "اجازه‌ی انتشار مدل ندارید",
        "error",
        "کلید API دامنه‌ی ml:publish ندارد، متعلق به سازمان ناشر نیست، فهرست IPهای مجاز آن خالی است، یا انتشار هنوز در تنظیمات سرور فعال نشده است.",
        [
            "با اسکریپت create_ml_publisher_key.py کلید ناشر بسازید و IP سرور GPU را در فهرست مجاز آن بگذارید.",
            "مدیر سامانه باید مقدار ML_PUBLISHER_TENANT_ID را در تنظیمات سرور تعیین کند.",
        ],
        "کلید ناشر و فهرست IP مجاز را بررسی کنید.",
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
        "علائم: درخواست مربوط به مخزن مدل‌ها با خطا برگشت داده شد.",
        f"علت: {cause}",
        steps,
        "برای اطمینان، همان کار را دوباره انجام دهید؛ اگر باز هم خطا گرفتید با پشتیبانی تماس بگیرید و این کد را بگویید: "
        + code,
        "پیشگیری: نسخه‌ها را یکتا بسازید و پیش از انتشار SHA-256 فایل را بررسی کنید.",
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
