"""Help article and error page for event SMS notifications."""

# ruff: noqa: E501 - the article text is long Persian prose that does not wrap usefully

import importlib.util
from pathlib import Path

import sqlalchemy as sa

from alembic import op

revision = "0135_sms_notifications_help"
down_revision = "0134_tenant_backup_requests"
branch_labels = None
depends_on = None

CATEGORY_SLUG = "plans-and-billing"
ARTICLE = (
    "sms-notifications",
    "پیامک اعلان‌های اشتراک و مصرف",
    "رویدادهای مهم حساب شما، مثل پرداخت، تمدید و رسیدن به سقف مصرف، با پیامک به مدیر سازمان اعلام می‌شود.",
    [
        "پیامک‌ها به شماره موبایل مدیران سازمان ارسال می‌شود: خوش‌آمدگویی پس از ثبت‌نام، پرداخت موفق، نزدیک‌شدن سررسید تمدید، پایان دوره آزمایشی، ورود به مهلت تمدید و پایان اشتراک.",
        [
            "وقتی ۸۰٪ و ۹۵٪ دقیقه‌های پلن یا توکن هوش مصنوعی مصرف شود، یک پیامک هشدار می‌آید و هنگام اتمام اعتبار پیامک آخر ارسال می‌شود.",
            "هر پیامک در هر دوره فقط یک‌بار ارسال می‌شود، حتی اگر رویداد چند بار بررسی شود.",
            "اگر شماره موبایل مدیر ثبت نشده باشد، پیامکی ارسال نمی‌شود؛ شماره را در پروفایل ذخیره کنید.",
            "مدیر پلتفرم قالب هر رویداد را در «تنظیمات ← قالب‌های پیامک» تعیین و فعال می‌کند و می‌تواند وضعیت ارسال‌ها را ببیند.",
        ],
        "اگر پیامکی نرسید، شماره موبایل مدیر سازمان و وضعیت ارسال را در بخش «آخرین ارسال‌ها» بررسی کنید.",
    ],
)
ERROR = (
    "sms_provider_error",
    "ارسال پیامک انجام نشد",
    "warning",
    "سرویس پیامک درخواست را نپذیرفت یا در دسترس نبود.",
    [
        "کلید API سرویس SMS.ir را در «تست سریع و پیامک» بررسی کنید.",
        "شناسه قالب خدماتی و نام پارامترها را با قالب تأییدشده در پنل SMS.ir مقایسه کنید.",
        "اعتبار پنل SMS.ir را بررسی و چند دقیقه بعد دوباره امتحان کنید.",
    ],
    "کلید API و شناسه قالب را در تنظیمات پیامک بررسی کنید.",
)


def _billing() -> object:
    path = Path(__file__).with_name("0069_billing_help_content.py")
    spec = importlib.util.spec_from_file_location("billing_help_0069", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def upgrade() -> None:
    helper = _billing()
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
    slug, title, summary, blocks = ARTICLE
    body_html, body_plain = helper._body(blocks)  # type: ignore[attr-defined]
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
            "position": 10,
        },
    )
    code, etitle, severity, cause, steps, quick = ERROR
    body_html, body_plain = helper._body(helper.error_blocks(cause, steps, code))  # type: ignore[attr-defined]
    error_slug = helper._slug(code)  # type: ignore[attr-defined]
    bind.execute(
        insert_article,
        {
            "slug": error_slug,
            "category": category_id,
            "title": etitle,
            "summary": cause,
            "html": body_html,
            "plain": body_plain,
            "kind": "error",
            "position": 110,
        },
    )
    bind.execute(
        sa.text(
            "INSERT INTO help_error_codes (code, article_id, source, severity, title, quick_action) "
            "SELECT :code, id, 'api', :severity, :title, :quick FROM help_articles WHERE slug = :slug "
            "ON CONFLICT (code) DO NOTHING"
        ),
        {"code": code, "severity": severity, "title": etitle, "quick": quick, "slug": error_slug},
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM help_error_codes WHERE code = :code"), {"code": ERROR[0]})
    bind.execute(
        sa.text("DELETE FROM help_articles WHERE slug = ANY(:slugs)"),
        {"slugs": [ARTICLE[0], "error-sms-provider-error"]},
    )
