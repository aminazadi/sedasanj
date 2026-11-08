"""Publish help for local-model assistant failures (no tool call, slow answer)."""

# ruff: noqa: E501 - Persian help prose is kept in complete paragraphs.

import sqlalchemy as sa

from alembic import op

revision = "0124_local_model_assistant_help"
down_revision = "0123_footer_address_help"
branch_labels = None
depends_on = None

# (slug, title, summary, body, error code, severity, quick action, plain-text keywords)
ARTICLES = [
    (
        "assistant-model-no-tools",
        "مدل دستیار ابزار ساخت فایل را اجرا نکرد",
        "رفع خطای assistant_model_no_tools وقتی مدل محلی به‌جای ابزار فقط متن می‌نویسد.",
        "<h2>نشانه‌ها</h2><p>پس از درخواست فایل (مثلاً اکسل) دستیار خطای "
        '<code dir="ltr">assistant_model_no_tools</code> نشان می‌دهد و فایلی ساخته نمی‌شود.</p>'
        "<h2>علت</h2><p>مدل انتخاب‌شده، معمولاً یک مدل محلی کوچک، دو بار به درخواست فراخوانی ابزار "
        "پاسخ متنی داد. چنین متنی ممکن است ادعا کند فایل آماده است، در حالی که هیچ ابزاری اجرا نشده؛ "
        "به همین دلیل دستیار آن را نمایش نمی‌دهد.</p>"
        "<h2>رفع مشکل</h2><ol>"
        "<li>مدیر سامانه در تنظیمات ← مدل‌ها و مسیرها ← «مدل دستیار سازمانی» مدل بزرگ‌تر یا دارای "
        "پشتیبانی ابزار را انتخاب کند (مثلاً مدل 9Router).</li>"
        "<li>مسیر دستیار را روی «/v1/chat/tasks — صف durable AISERVICE» بگذارد.</li>"
        "<li>درخواست را کوتاه و دقیق بفرستید: دسته داده، قالب فایل و بازه زمانی را بنویسید.</li>"
        "</ol><h2>تأیید رفع مشکل</h2><p>فایل ساخته‌شده با لینک دریافت در پاسخ دستیار دیده می‌شود.</p>"
        "<h2>پیشگیری</h2><p>برای ابزارها و ساخت فایل از مدلی استفاده کنید که فراخوانی ابزار را "
        "درست انجام می‌دهد؛ مدل‌های ۴ میلیارد پارامتری معمولاً کافی نیستند.</p>",
        "assistant_model_no_tools",
        "warning",
        "مدل دیگری برای دستیار انتخاب کنید یا مسیر durable را فعال کنید.",
    ),
    (
        "ai-local-model-timeout",
        "پاسخ مدل محلی در زمان مقرر نرسید",
        "رفع خطای llm_provider_timeout و حالت «پاسخ در لاگ سرویس هست ولی در پنل نیست».",
        "<h2>نشانه‌ها</h2><p>در لاگ سرویس هوش مصنوعی پاسخ کامل دیده می‌شود، اما دستیار یا بخش دیگر "
        'پنل خطای <code dir="ltr">llm_provider_timeout</code> یا «پاسخ آماده نشد» نشان می‌دهد.</p>'
        '<h2>علت</h2><p>مسیر «پاسخ مستقیم» (<code dir="ltr">/v1/chat/completions</code>) تا پایان '
        "تولید منتظر می‌ماند. مدل محلی روی CPU با پرامپت بلند ممکن است از مهلت بیشتر طول بکشد.</p>"
        "<h2>رفع مشکل</h2><ol>"
        "<li>مسیر را به «/v1/chat/tasks — صف durable AISERVICE» تغییر دهید؛ این مسیر منتظر نمی‌ماند "
        "و نتیجه را پیگیری می‌کند.</li>"
        "<li>اگر مسیر مستقیم لازم است، مدیر سرور مقدار "
        '<code dir="ltr">VOICESANJ_SYNC_READ_TIMEOUT_SECONDS</code> را (پیش‌فرض ۱۲۰ ثانیه، حداکثر ۶۰۰) '
        "افزایش دهد.</li>"
        "<li>مدل سبک‌تر انتخاب کنید یا تاریخچهٔ گفتگو را کوتاه‌تر کنید.</li>"
        "</ol><h2>تأیید رفع مشکل</h2><p>همان پیام را دوباره بفرستید؛ پاسخ باید بدون خطا نمایش داده شود.</p>"
        "<h2>پیشگیری</h2><p>برای مدل‌های محلی از مسیر durable استفاده کنید.</p>",
        "llm_provider_timeout",
        "warning",
        "مسیر را روی durable بگذارید یا مدل سبک‌تر انتخاب کنید.",
    ),
]


def upgrade() -> None:
    bind = op.get_bind()
    for slug, title, summary, body, code, severity, quick in ARTICLES:
        bind.execute(
            sa.text(
                "INSERT INTO help_articles (slug, title, summary, body_html, body_plain, kind, "
                "status, position, published_at) VALUES (:slug, :title, :summary, :body, "
                ":plain, 'article', 'published', 152, now()) ON CONFLICT (slug) DO NOTHING"
            ),
            {
                "slug": slug,
                "title": title,
                "summary": summary,
                "body": body,
                "plain": f"{title} {code}",
            },
        )
        bind.execute(
            sa.text(
                "INSERT INTO help_error_codes (code, article_id, source, severity, title, quick_action) "
                "SELECT :code, id, 'api', :severity, :title, :quick FROM help_articles "
                "WHERE slug = :slug ON CONFLICT (code) DO NOTHING"
            ),
            {"code": code, "severity": severity, "title": title, "quick": quick, "slug": slug},
        )


def downgrade() -> None:
    bind = op.get_bind()
    codes = [item[4] for item in ARTICLES]
    slugs = [item[0] for item in ARTICLES]
    bind.execute(sa.text("DELETE FROM help_error_codes WHERE code = ANY(:codes)"), {"codes": codes})
    bind.execute(sa.text("DELETE FROM help_articles WHERE slug = ANY(:slugs)"), {"slugs": slugs})
