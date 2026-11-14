"""Help article and error page for payment failure codes."""

# ruff: noqa: E501 - the article text is long Persian prose that does not wrap usefully

import importlib.util
from pathlib import Path

import sqlalchemy as sa

from alembic import op

revision = "0137_payment_failure_codes_help"
down_revision = "0136_grant_balance_checks"
branch_labels = None
depends_on = None

CATEGORY_SLUG = "plans-and-billing"
ARTICLE = (
    "payment-failure-codes",
    "کدهای ناموفق‌بودن پرداخت",
    "معنی کدهایی که کنار پرداخت‌های ناموفق یا نیازمند بررسی می‌بینید و کاری که باید کرد.",
    [
        "اگر پرداختی فعال نشد، کد زیر در جدول پرداخت‌ها دیده می‌شود و نشان می‌دهد چرا.",
        [
            "bank_reference_reused: شماره پیگیری بانک قبلاً برای پرداخت دیگری ثبت شده بود؛ این پرداخت پذیرفته نمی‌شود و مبلغ طبق قواعد بانک برمی‌گردد.",
            "order_canceled: سفارش هنگام پرداخت ابطال شده بود؛ فعال‌سازی انجام نمی‌شود و مبلغ باید به مشتری برگردد.",
            "fulfill_failed:...: پول دریافت شده ولی اعمال سفارش خطا داد؛ سیستم خودکار دوباره تلاش می‌کند. اگر برطرف نشد «تطبیق امن» را بزنید.",
            "needs_attention: سفارش پرداخت شده اما تغییر پلن اعمال نشد؛ بررسی دستی لازم است.",
        ],
        "برای هر مورد شماره سفارش را نگه دارید و در صورت نیاز با «تطبیق امن» یا بازپرداخت دستی اقدام کنید.",
    ],
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


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text("DELETE FROM help_articles WHERE slug = ANY(:slugs)"),
        {"slugs": [ARTICLE[0]]},
    )
