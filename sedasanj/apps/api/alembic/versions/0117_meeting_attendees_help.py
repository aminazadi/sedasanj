"""Help-center article for choosing the people present before recording a Jalase-Negar meeting."""

# ruff: noqa: E501 - the article text is long Persian prose that does not wrap usefully

import html

import sqlalchemy as sa

from alembic import op

revision = "0117_meeting_attendees_help"
down_revision = "0116_meeting_attendees"
branch_labels = None
depends_on = None

CATEGORY_SLUG = "meetings"
SLUG = "jalase-negar-meeting-attendees"
TITLE = "انتخاب حاضران جلسه پیش از ضبط"
SUMMARY = (
    "انتخاب یا افزودن افراد حاضر در صفحه ضبط جلسه‌نگار، اثر آن بر تشخیص گوینده و پیام JN-REC-0005."
)
BLOCKS = [
    "نشانه‌ها: حاضران جلسه در پنل دیده نمی‌شوند، گوینده‌ها با نام درست شناخته نمی‌شوند یا هنگام ضبط پیام JN-REC-0005 در گزارش اشکال‌زدایی ثبت شده است.",
    "علت: حاضران را پیش از شروع ضبط، در کارت «حاضران جلسه (اختیاری)» انتخاب می‌کنید. ثبت حاضران برای اجرای ضبط ضروری نیست؛ اگر ذخیره‌شان روی گوشی انجام نشود، ضبط ادامه می‌یابد و کد JN-REC-0005 ثبت می‌شود. فرد تازه‌ای که هنوز با سرور همگام نشده، با نام در پنل نمایش داده می‌شود.",
    [
        "در جلسه‌نگار، صفحه ضبط را باز کنید و روی کارت «حاضران جلسه (اختیاری)» بزنید.",
        "افراد حاضر را تیک بزنید. برای فرد تازه، «افزودن فرد جدید» را بزنید، متن را بخوانید، نام را بنویسید، رضایت را تأیید و ذخیره کنید؛ فرد جدید خودکار انتخاب می‌شود.",
        "«تأیید» را بزنید و ضبط را شروع کنید.",
        "پس از ضبط، فهرست حاضران را در جزئیات جلسه ببینید. اگر نبود، همین مراحل را برای ضبط بعدی تکرار کنید و ساعاتی بعد، پنل را دوباره باز کنید.",
        "اگر در پنل حاضران دیده نمی‌شوند، در جلسه‌نگار «افراد» را باز کنید تا همگام‌سازی کامل شود و جلسه را دوباره بفرستید.",
    ],
    "اثر بر تشخیص گوینده: صدای حاضران انتخاب‌شده در تطبیق صدا کمی برتری دارد، ولی بقیه افراد ثبت‌شده هم همچنان شناسایی می‌شوند. صورت‌جلسه نیز نام حاضران را در بخش شرکت‌کنندگان می‌آورد.",
    "پیشگیری: پیش از جلسه، افرادی را که صدایشان ثبت شده است انتخاب کنید و فرد تازه را پیش از شروع ضبط بسازید، نه وسط آن.",
]


def _body() -> tuple[str, str]:
    parts: list[str] = []
    plain: list[str] = []
    for block in BLOCKS:
        if isinstance(block, list):
            parts.append(
                "<ol>" + "".join(f"<li>{html.escape(step)}</li>" for step in block) + "</ol>"
            )
            plain.extend(block)
        else:
            parts.append(f"<p>{html.escape(block)}</p>")
            plain.append(block)
    return "".join(parts), " ".join(plain)


def upgrade() -> None:
    bind = op.get_bind()
    category_id = bind.execute(
        sa.text("SELECT id FROM help_categories WHERE slug = :slug"), {"slug": CATEGORY_SLUG}
    ).scalar_one()
    body_html, body_plain = _body()
    bind.execute(
        sa.text(
            "INSERT INTO help_articles (slug, category_id, title, summary, body_html, body_plain, "
            "kind, status, position, published_at) "
            "VALUES (:slug, :category, :title, :summary, :html, :plain, 'article', 'published', 23, now()) "
            "ON CONFLICT (slug) DO NOTHING"
        ),
        {
            "slug": SLUG,
            "category": category_id,
            "title": TITLE,
            "summary": SUMMARY,
            "html": body_html,
            "plain": body_plain,
        },
    )


def downgrade() -> None:
    op.get_bind().execute(sa.text("DELETE FROM help_articles WHERE slug = :slug"), {"slug": SLUG})
