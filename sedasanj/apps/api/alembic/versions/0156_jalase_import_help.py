"""Help for copying personal Jalase-Negar meetings into a linked organization."""

# ruff: noqa: E501 - Persian help prose is kept in complete paragraphs.

import sqlalchemy as sa

from alembic import op

revision = "0156_jalase_import_help"
down_revision = "0155_jalase_links_help"
branch_labels = None
depends_on = None

SLUG = "jalase-negar-link-organization"
CODE = "import_document_purged"
EXTRA = (
    "<h2>کپی جلسه‌های شخصی به سازمان</h2><p>پس از اتصال می‌توانید جلسه‌های تمام‌شدهٔ شخصی را انتخاب کنید و به سازمان کپی کنید. اصل جلسه در حساب شخصی می‌ماند. "
    '<code dir="ltr">import_document_purged</code>: جلسه‌ای که با گزینهٔ «بدون نگهداری» پاک شده متنی ندارد و کپی نمی‌شود؛ آن را از انتخاب خارج کنید.</p>'
)


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE help_articles SET body_html = body_html || :extra WHERE slug = :slug "
            "AND position(:extra in body_html) = 0"
        ),
        {"slug": SLUG, "extra": EXTRA},
    )
    bind.execute(
        sa.text(
            "INSERT INTO help_error_codes (code,source,severity,article_id,title,quick_action) "
            "SELECT :code,'api','error',id,:title,:action "
            "FROM help_articles WHERE slug=:slug ON CONFLICT (code) DO NOTHING"
        ),
        {
            "slug": SLUG,
            "code": CODE,
            "title": "این جلسه متنی برای کپی ندارد (پاک شده است).",
            "action": "جلسهٔ پاک‌شده را از انتخاب خارج کنید.",
        },
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM help_error_codes WHERE code=:code"), {"code": CODE})
    bind.execute(
        sa.text("UPDATE help_articles SET body_html = replace(body_html, :extra, '') WHERE slug = :slug"),
        {"slug": SLUG, "extra": EXTRA},
    )
