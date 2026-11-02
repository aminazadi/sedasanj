"""Seed the help-center articles and error-code pages for meetings."""

# ruff: noqa: E501 - the article text is long Persian prose that does not wrap usefully

import html

import sqlalchemy as sa

from alembic import op

revision = "0094_meetings_help_content"
down_revision = "0093_meetings"
branch_labels = None
depends_on = None

CATEGORY = ("meetings", "جلسه‌ها", "اتصال اپ جلسه‌نگار، ارسال صدا و پردازش جلسه")

ARTICLES = [
    (
        "meetings-overview",
        "جلسه‌ها در صداسنج",
        "اپ جلسه‌نگار جلسه را ضبط و تکه‌تکه ارسال می‌کند؛ رونویسی، تفکیک گوینده و صورت‌جلسه در صداسنج ساخته می‌شود.",
        [
            "هر جلسه فقط برای صاحب آن و مدیران سازمان دیده می‌شود. هزینه جلسه از همان اعتبار ثانیه‌ای تماس‌ها کم می‌شود.",
            [
                "اپ جلسه‌نگار را از «پروفایل» به حساب خود متصل کنید.",
                "جلسه را در اپ ضبط کنید؛ صدا هر حدود یک دقیقه ارسال می‌شود.",
                "بعد از پایان ضبط، در صفحه «جلسات» پیشرفت پردازش را ببینید.",
                "پس از کامل شدن، متن با گوینده‌ها و صورت‌جلسه نمایش داده می‌شود.",
            ],
            "فایل صدا طبق مدت نگهداری صدای سازمان حذف می‌شود؛ متن و صورت‌جلسه می‌ماند.",
        ],
    ),
    (
        "meetings-connect-app",
        "اتصال اپ جلسه‌نگار",
        "با یک کد یک‌بارمصرف، اپ توکن شخصی شما را می‌گیرد؛ کد یا QR توکن بلندمدت ندارد.",
        [
            "کد جفت‌سازی ۱۵ دقیقه معتبر است و فقط یک بار کار می‌کند. هر کاربر تا ۵ دستگاه فعال می‌تواند داشته باشد.",
            [
                "در «پروفایل» روی ساخت کد اتصال بزنید.",
                "در اپ، QR را اسکن کنید یا فایل کانفیگ را انتخاب کنید یا کد را بچسبانید.",
                "اگر دستگاهی را گم کرده‌اید، آن را از فهرست دستگاه‌ها ابطال کنید.",
            ],
            "پس از ابطال، اپ همان دستگاه با خطای دسترسی روبه‌رو می‌شود و باید دوباره جفت شود.",
        ],
    ),
    (
        "meetings-processing-states",
        "وضعیت‌های پردازش جلسه",
        "دریافت، پردازش، کامل، ناموفق و لغو‌شده؛ هر وضعیت یعنی چه و چه کاری لازم است.",
        [
            "در حال دریافت: اپ هنوز صدا می‌فرستد یا تکه‌هایی کم است. در حال پردازش: ضبط تمام شده و رونویسی و صورت‌جلسه در جریان است.",
            [
                "کامل: متن و صورت‌جلسه آماده است.",
                "ناموفق: دکمه «تلاش مجدد» را بزنید؛ اگر بخشی از صدا رونویسی نشده، همان بخش دوباره پردازش می‌شود.",
                "لغو‌شده: اعتبار رزروشده برگردانده شده است.",
            ],
            "اگر صورت‌جلسه خوب نبود، «بازتحلیل» نسخه جدیدی می‌سازد و هزینه‌ای ندارد.",
        ],
    ),
]

# code, title, severity, cause, steps, quick action
ERRORS = [
    ("meeting_not_found", "جلسه پیدا نشد", "warning",
     "جلسه حذف شده یا متعلق به کاربر دیگری است.",
     ["فهرست جلسه‌ها را تازه کنید.", "اگر از اپ می‌فرستید، جلسه جدید شروع کنید."],
     "فهرست جلسه‌ها را تازه کنید."),
    ("meeting_closed", "جلسه بسته شده است", "warning",
     "ضبط این جلسه تمام، لغو یا در حال پردازش است و تکه جدید نمی‌پذیرد.",
     ["در اپ جلسه جدید شروع کنید.", "برای دیدن نتیجه، صفحه «جلسات» را باز کنید."],
     "جلسه جدید شروع کنید."),
    ("meeting_chunk_conflict", "تکه با محتوای دیگر ثبت شده", "warning",
     "برای همین شماره تکه قبلاً صدای متفاوتی دریافت شده است.",
     ["وضعیت جلسه را بخوانید و فقط تکه‌های گم‌شده را بفرستید.", "اگر تکرار شد، جلسه را لغو و دوباره ضبط کنید."],
     "از وضعیت جلسه ادامه دهید."),
    ("meeting_incomplete_chunks", "تکه‌هایی هنوز نرسیده‌اند", "warning",
     "هنگام پایان جلسه بعضی تکه‌ها دریافت نشده بودند.",
     ["شماره تکه‌های گم‌شده در پاسخ آمده است؛ همان‌ها را دوباره بفرستید.", "سپس پایان جلسه را دوباره بزنید."],
     "تکه‌های گم‌شده را دوباره بفرستید."),
    ("meeting_chunk_too_large", "تکه صدا بزرگ است", "warning",
     "حجم تکه از سقف مجاز بیشتر است.",
     ["تکه‌ها را کوتاه‌تر کنید (حدود ۶۰ ثانیه).", "اپ را به‌روز کنید."],
     "تکه‌ها را کوتاه‌تر کنید."),
    ("meeting_chunk_invalid_audio", "فرمت صدا نامعتبر است", "warning",
     "فایل WAV تک‌کاناله، ۱۶ کیلوهرتز و ۱۶ بیتی نیست یا هش آن با محتوا نمی‌خواند.",
     ["تکه را از روی فایل محلی دوباره بفرستید.", "اپ را به‌روز کنید تا فرمت درست تولید شود."],
     "WAV تک‌کاناله ۱۶ کیلوهرتز بفرستید."),
    ("meeting_token_limit", "سقف دستگاه‌ها پر است", "warning",
     "پنج دستگاه فعال به حساب شما متصل است.",
     ["در «پروفایل» فهرست دستگاه‌ها را باز کنید.", "یک دستگاه بی‌استفاده را ابطال و دوباره جفت کنید."],
     "یک دستگاه را ابطال کنید."),
    ("meeting_pairing_invalid", "کد اتصال نامعتبر است", "warning",
     "کد اشتباه، منقضی (بیش از ۱۵ دقیقه) یا قبلاً استفاده شده است.",
     ["در «پروفایل» کد جدید بسازید.", "کد را همان لحظه در اپ وارد یا QR را اسکن کنید."],
     "کد جدید بسازید."),
    ("meeting_asr_failed", "رونویسی جلسه ناموفق بود", "error",
     "تبدیل بخشی از صدا به متن با خطا مواجه شد.",
     ["چند دقیقه صبر کنید؛ تلاش خودکار انجام می‌شود.", "اگر ماند، در جزئیات جلسه «تلاش مجدد» را بزنید."],
     "«تلاش مجدد» را بزنید."),
    ("meeting_diarization_failed", "تفکیک گوینده ناموفق بود", "warning",
     "گوینده‌ها قابل تشخیص نبودند؛ متن بدون نام گوینده تحویل شد.",
     ["متن و صورت‌جلسه را همچنان می‌توانید ببینید.", "در صورت نیاز گوینده‌ها را دستی نام‌گذاری کنید."],
     "متن بدون گوینده قابل استفاده است."),
    ("meeting_minutes_failed", "ساخت صورت‌جلسه ناموفق بود", "error",
     "تولید صورت‌جلسه با خطا مواجه شد؛ متن جلسه سالم است.",
     ["در جزئیات جلسه «بازتحلیل» را بزنید.", "اگر تکرار شد با پشتیبانی تماس بگیرید."],
     "«بازتحلیل» را بزنید."),
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
