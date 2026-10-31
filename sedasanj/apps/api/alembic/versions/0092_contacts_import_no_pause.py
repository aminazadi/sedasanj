"""Update contact import help for uninterrupted sequential uploads."""

import sqlalchemy as sa

from alembic import op

revision = "0092_contacts_import_no_pause"
down_revision = "0091_task_workspace"
branch_labels = None
depends_on = None

OLD_TEXT = "محدودیت تعداد درخواست‌ها باعث مکث خودکار و سپس ادامه می‌شود."
NEW_TEXT = "بخش‌های فایل بدون مکث اجباری و پشت‌سرهم ارسال می‌شوند."


def _replace(previous: str, replacement: str) -> None:
    op.get_bind().execute(
        sa.text(
            "UPDATE help_articles SET body_html = replace(body_html, :previous, :replacement), "
            "body_plain = replace(body_plain, :previous, :replacement) WHERE slug = :slug"
        ),
        {
            "previous": previous,
            "replacement": replacement,
            "slug": "contacts-csv-import-guide",
        },
    )


def upgrade() -> None:
    _replace(OLD_TEXT, NEW_TEXT)


def downgrade() -> None:
    _replace(NEW_TEXT, OLD_TEXT)
