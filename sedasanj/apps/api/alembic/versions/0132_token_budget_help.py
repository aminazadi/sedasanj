"""Help article and error page for the per-plan LLM token budget."""

# ruff: noqa: E501 - the article text is long Persian prose that does not wrap usefully

import importlib.util
from pathlib import Path

import sqlalchemy as sa

from alembic import op

revision = "0132_token_budget_help"
down_revision = "0131_plan_llm_token_budget"
branch_labels = None
depends_on = None

CATEGORY_SLUG = "plans-and-billing"
ARTICLE = (
    "llm-token-budget",
    "سهمیه توکن هوش مصنوعی",
    "هر پلن یک سقف ماهانه توکن برای پردازش‌های هوش مصنوعی دارد و مصرف دقیقاً از عدد اعلام‌شده سرویس هوش مصنوعی حساب می‌شود.",
    [
        "توکن‌های مصرفی تحلیل تماس، صورت‌جلسه، دستیار، گزارش‌های زمان‌بندی‌شده و جست‌وجوی دانش از همان عددی که سرویس هوش مصنوعی برمی‌گرداند ثبت می‌شود؛ هیچ مقداری تخمین زده نمی‌شود. پردازش گفتار (ASR) با ثانیه صوت و از همان دقیقه‌های پلن حساب می‌شود.",
        [
            "مصرف و باقی‌مانده توکن ماه جاری را در «حساب» ببینید؛ شمارش از تاریخ سالگرد شروع اشتراک است.",
            "اگر سرویس هوش مصنوعی عدد مصرف را اعلام نکند، آن مورد جدا شمرده و در پنل مدیریت نشان داده می‌شود و صفر حساب نمی‌شود.",
            "پس از پایان سقف پلن، توکن خریداری‌شده (بسته توکن) مصرف می‌شود.",
            "وقتی توکن پلن و بسته‌ها تمام شود، درخواست‌های جدید هوش مصنوعی رد می‌شود؛ کارهایی که پیش از آن شروع شده‌اند ادامه می‌یابند.",
        ],
        "برای ادامه کار، بسته توکن بخرید، پلن را ارتقا دهید یا تا شروع دوره بعد صبر کنید.",
    ],
)
ERROR = (
    "token_quota_exceeded",
    "سهمیه توکن هوش مصنوعی تمام شده است",
    "error",
    "توکن ماهانه پلن و بسته‌های توکن خریداری‌شده برای درخواست‌های جدید هوش مصنوعی تمام شده است.",
    [
        "در «حساب» مصرف توکن این ماه را ببینید.",
        "بسته توکن بخرید یا پلن را ارتقا دهید.",
        "اگر ترجیح می‌دهید، تا شروع دوره بعد (تاریخ سالگرد اشتراک) صبر کنید.",
    ],
    "بسته توکن بخرید یا پلن را ارتقا دهید.",
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
        {"slugs": [ARTICLE[0], "error-token-quota-exceeded"]},
    )
