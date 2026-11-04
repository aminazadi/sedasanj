"""Help-center articles and error pages for the Jalase-Negar Android update flow."""

# ruff: noqa: E501 - the article text is long Persian prose that does not wrap usefully

import html

import sqlalchemy as sa

from alembic import op

revision = "0098_jalase_negar_update_help_content"
down_revision = "0097_jalase_negar_releases"
branch_labels = None
depends_on = None

CATEGORY_SLUG = "meetings"

ARTICLES = [
    (
        "jalase-negar-android-update",
        "به‌روزرسانی جلسه‌نگار اندروید",
        "اپ در هر اجرا نسخه جدید را بررسی می‌کند و فایل نصب را از سرور صداسنج به شما پیشنهاد می‌دهد.",
        [
            "جلسه‌نگار هنگام باز شدن اپ، حتی پیش از اتصال به سازمان، از سرور مرکزی صداسنج می‌پرسد نسخه تازه‌تری برای گوشی شما هست یا نه. اگر باشد، بعد از ورود به صفحه جلسات و پایان راهنمای اپ پنجره‌ای با نسخه و تغییرات نمایش داده می‌شود. جلسه‌ها، فایل‌های صدا و مدل‌های دانلودشده با به‌روزرسانی پاک نمی‌شوند.",
            [
                "در پنجره پیشنهاد، «دریافت نسخه» را بزنید تا فایل در مرورگر گوشی دانلود شود. اگر الان وقت ندارید «بعداً» را بزنید؛ پیشنهاد در اجرای بعدی اپ دوباره می‌آید.",
                "پس از دانلود، فایل را از اعلان مرورگر یا پوشه Downloads باز کنید.",
                "اگر اندروید خواست، در تنظیمات اجازه نصب برنامه از همان مرورگر را بدهید و به صفحه نصب برگردید.",
                "«به‌روزرسانی» را بزنید و پس از پایان نصب، جلسه‌نگار را باز کنید.",
            ],
            "برای بررسی دستی، در اپ به «تنظیمات» بروید و «بررسی به‌روزرسانی» را بزنید.",
        ],
    ),
    (
        "jalase-negar-android-update-troubleshooting",
        "رفع مشکل نصب نسخه جدید جلسه‌نگار",
        "اگر پیشنهاد نمی‌آید، دانلود قطع می‌شود یا نصب تمام نمی‌شود، این مراحل را به ترتیب انجام دهید.",
        [
            "پیشنهاد فقط برای گوشی‌ای نمایش داده می‌شود که نسخه فعلی آن امضای رسمی جلسه‌نگار را دارد و نسخه جدید روی همان مدل گوشی قابل نصب است.",
            [
                "اینترنت گوشی را بررسی کنید و در «تنظیمات» اپ دوباره «بررسی به‌روزرسانی» را بزنید.",
                "اگر دانلود نیمه‌کاره ماند، دوباره «دریافت نسخه» را بزنید؛ مرورگر دانلود را از ادامه می‌گیرد.",
                "اگر اندروید می‌گوید برنامه با نسخه نصب‌شده تداخل دارد، اپ را حذف نکنید؛ با پشتیبانی تماس بگیرید تا مسیر حفظ اطلاعات بررسی شود.",
                "اگر پیام «نصب نشد» دیدید، فضای خالی گوشی را بررسی کنید و فایل را دوباره باز کنید.",
            ],
            "حذف اپ پیش از به‌روزرسانی، جلسه‌ها و صداهای ذخیره‌شده روی گوشی را پاک می‌کند؛ این کار را انجام ندهید.",
        ],
    ),
]

# code, title, severity, cause, steps, quick action
ERRORS = [
    ("apk_invalid", "فایل APK نامعتبر است", "warning",
     "فایل بارگذاری‌شده APK کامل و امضاشده با کلید رسمی جلسه‌نگار نیست، یا شناسه بسته، امضا یا مشخصات آن درست نیست.",
     ["مطمئن شوید فایل خروجی release است، نه debug و نه app bundle.", "APK را با کلید رسمی امضا کنید و با apksigner verify بررسی کنید.", "شناسه بسته باید app.jalasenegar.jalase_negar باشد؛ فایل را دوباره بارگذاری کنید."],
     "APK رسمی را دوباره بسازید و بارگذاری کنید."),
    ("apk_inspection_unavailable", "بررسی APK روی سرور ممکن نیست", "error",
     "ابزار بررسی APK روی سرور نصب نیست یا اثرانگشت گواهی امضای رسمی در تنظیمات استقرار ثبت نشده است.",
     ["از مدیر سرور بخواهید aapt2 و apksigner را نصب کنند.", "مقدار JALASE_NEGAR_APK_CERT_SHA256 را در تنظیمات استقرار بررسی و سرویس API را راه‌اندازی مجدد کنید.", "چند دقیقه بعد APK را دوباره بارگذاری کنید."],
     "تنظیمات بررسی APK را کامل کنید."),
    ("release_version_conflict", "تداخل شماره نسخه", "warning",
     "شماره ساخت (versionCode) یا نام نسخه قبلاً ثبت شده، یا از نسخه‌های منتشرشده و لغوشده پایین‌تر نیست.",
     ["در pubspec.yaml عدد بعد از + را از آخرین نسخه منتشرشده یا لغوشده بزرگ‌تر کنید.", "APK را دوباره بسازید و بارگذاری کنید.", "اگر هم‌زمان دو نفر منتشر می‌کردند، فهرست نسخه‌ها را تازه کنید."],
     "شماره ساخت بالاتر بدهید."),
    ("release_file_unavailable", "فایل نسخه در دسترس نیست", "error",
     "فایل APK در فضای ذخیره‌سازی پیدا نشد یا ذخیره‌سازی موقتاً پاسخ نمی‌دهد.",
     ["چند دقیقه بعد دوباره تلاش کنید.", "اگر خطا ادامه داشت، سلامت ذخیره‌سازی فایل را در پایش بررسی کنید.", "اگر فایل واقعاً از بین رفته، پیش‌نویس را حذف و APK را دوباره بارگذاری کنید."],
     "دقایقی بعد دوباره تلاش کنید."),
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
        "علائم: بارگذاری، انتشار یا دانلود نسخه جلسه‌نگار با خطا برگشت داده شد.",
        f"علت: {cause}",
        steps,
        "برای اطمینان، همان کار را دوباره انجام دهید؛ اگر باز هم خطا گرفتید با پشتیبانی تماس بگیرید و این کد را بگویید: "
        + code,
        "پیشگیری: پیش از هر انتشار، APK را با ابزار بررسی بسنجید و شماره ساخت را همیشه افزایش دهید.",
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
                "position": 20 + position,
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
