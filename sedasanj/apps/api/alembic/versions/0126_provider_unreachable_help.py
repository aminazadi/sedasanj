"""Publish help for AI provider outages (job parked, then reattached)."""

# ruff: noqa: E501 - Persian help prose is kept in complete paragraphs.

import sqlalchemy as sa

from alembic import op

revision = "0126_provider_unreachable_help"
down_revision = "0125_ai_usage_events"
branch_labels = None
depends_on = None

_BODY = (
    "<h2>نشانه‌ها</h2><p>کار در وضعیت «تلاش مجدد» می‌ماند و خطای "
    '<code dir="ltr">{code}</code> دیده می‌شود.</p>'
    "<h2>علت</h2><p>سرویس هوش مصنوعی (aiservice) موقتاً در دسترس نیست: ری‌استارت، قطع شبکه یا فشار "
    "زیاد. این خطا از خود تماس نیست و تلاش‌های مجاز کار را مصرف نمی‌کند.</p>"
    "<h2>رفع مشکل</h2><ol>"
    "<li>نیازی به اقدام نیست؛ کار هر ۶۰ ثانیه تا ۲۴ ساعت دوباره تلاش می‌شود و به همان وظیفهٔ "
    "قبلی در سرویس وصل می‌شود، نه یک وظیفهٔ تکراری.</li>"
    "<li>اگر خطا بیش از چند دقیقه ماند، مدیر سامانه وضعیت aiservice و آدرس پایهٔ آن را در "
    "تنظیمات مدل‌ها بررسی کند.</li>"
    "</ol><h2>تأیید رفع مشکل</h2><p>وضعیت کار پس از برگشت سرویس به «در حال انجام» و سپس «انجام شد» "
    "تغییر می‌کند.</p>"
    "<h2>پیشگیری</h2><p>برای ری‌استارت aiservice از حالت توقف تدریجی استفاده کنید تا کارهای در "
    "حال اجرا کامل شوند.</p>"
)

# (slug, title, summary, code, quick action)
ARTICLES = [
    (
        "ai-provider-unreachable-asr",
        "سرویس پیاده‌سازی گفتار موقتاً در دسترس نیست",
        "توضیح خطای asr_provider_unreachable و اینکه کار خودکار دوباره تلاش می‌شود.",
        "asr_provider_unreachable",
        "منتظر بمانید؛ کار خودکار دوباره تلاش می‌شود.",
    ),
    (
        "ai-provider-unreachable-llm",
        "سرویس تحلیل متن موقتاً در دسترس نیست",
        "توضیح خطای llm_provider_unreachable و اینکه کار خودکار دوباره تلاش می‌شود.",
        "llm_provider_unreachable",
        "منتظر بمانید؛ کار خودکار دوباره تلاش می‌شود.",
    ),
]


def upgrade() -> None:
    bind = op.get_bind()
    for slug, title, summary, code, quick in ARTICLES:
        bind.execute(
            sa.text(
                "INSERT INTO help_articles (slug, title, summary, body_html, body_plain, kind, "
                "status, position, published_at) VALUES (:slug, :title, :summary, :body, "
                ":plain, 'article', 'published', 153, now()) ON CONFLICT (slug) DO NOTHING"
            ),
            {
                "slug": slug,
                "title": title,
                "summary": summary,
                "body": _BODY.format(code=code),
                "plain": f"{title} {code}",
            },
        )
        bind.execute(
            sa.text(
                "INSERT INTO help_error_codes (code, article_id, source, severity, title, quick_action) "
                "SELECT :code, id, 'api', 'warning', :title, :quick FROM help_articles "
                "WHERE slug = :slug ON CONFLICT (code) DO NOTHING"
            ),
            {"code": code, "title": title, "quick": quick, "slug": slug},
        )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text("DELETE FROM help_error_codes WHERE code = ANY(:codes)"),
        {"codes": [item[3] for item in ARTICLES]},
    )
    bind.execute(
        sa.text("DELETE FROM help_articles WHERE slug = ANY(:slugs)"),
        {"slugs": [item[0] for item in ARTICLES]},
    )
