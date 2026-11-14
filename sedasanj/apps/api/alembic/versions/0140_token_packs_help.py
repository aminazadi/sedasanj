"""Help article and error page for token pack purchases."""

# ruff: noqa: E501 - the article text is long Persian prose that does not wrap usefully

import importlib.util
from pathlib import Path

import sqlalchemy as sa

from alembic import op

revision = "0140_token_packs_help"
down_revision = "0139_tenant_restores"
branch_labels = None
depends_on = None

CATEGORY_SLUG = "plans-and-billing"
ARTICLE = (
    "token-packs",
    "خرید بسته توکن هوش مصنوعی",
    "وقتی توکن ماهانه پلن تمام شود، با خرید بسته توکن می‌توانید بدون ارتقای پلن ادامه دهید.",
    [
        "مدیر سازمان در «حساب ← خرید بسته توکن هوش مصنوعی» بسته را انتخاب و مثل هر خرید دیگری پرداخت می‌کند.",
        [
            "توکن بسته بعد از پایان توکن ماهانه پلن مصرف می‌شود و منقضی نمی‌شود.",
            "مصرف از عدد دقیقِ اعلام‌شده سرویس هوش مصنوعی حساب می‌شود.",
            "بازپرداخت فقط وقتی ممکن است که توکن بسته مصرف نشده باشد؛ سهم مصرف‌شده برگشت‌پذیر نیست.",
            "مدیر پلتفرم بسته‌ها را در «بسته‌های توکن» تعریف می‌کند و می‌تواند به یک سازمان توکن دستی بدهد.",
        ],
        "اگر پرداخت انجام شد ولی توکن اضافه نشد، شماره سفارش را برای پشتیبانی بفرستید.",
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
