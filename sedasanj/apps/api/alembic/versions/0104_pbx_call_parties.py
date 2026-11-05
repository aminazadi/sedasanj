"""Store independently resolved PBX call parties and their assignment roles."""

import sqlalchemy as sa

from alembic import op

revision = "0104_pbx_call_parties"
down_revision = "0103_account_access_help"
branch_labels = None
depends_on = None

_CALL_COLUMNS = (
    "caller_extension",
    "dialed_extension",
    "pbx_evidence",
    "raw_caller_number",
    "raw_dialed_number",
)


_ARTICLE = "pbx-operator-ownership"
_TITLE = "همگام‌سازی داخلی و انتساب اپراتور"
_SUMMARY = "اتصال سانترال، تشخیص داخلی پاسخ‌دهنده و بازبینی سوابق تماس"
_BODY = (
    "<h2>نشانه‌ها</h2><p>داخلی پاسخ‌دهنده مشخص نیست یا همگام‌سازی رد می‌شود.</p>"
    "<h2>علت</h2><p>ممکن است منبع همگام‌سازی عوض شده باشد یا گزارش تماس شواهد کافی "
    "برای تشخیص طرف پاسخ‌دهنده نداشته باشد. شماره صف یا گروه زنگ داخلی اپراتور نیست.</p>"
    "<h2>رفع مشکل</h2><ol><li>فهرست داخلی‌ها را در ماژول FreePBX همگام کنید.</li>"
    "<li>در صفحه داخلی‌ها اتصال هر داخلی به اپراتور را بررسی کنید.</li>"
    "<li>اگر سانترال عوض شده، مدیر سازمان اتصال قبلی را آزاد کند و از سانترال جدید "
    "همگام‌سازی را انجام دهد.</li>"
    "<li>تغییرات سوابق را در بازبینی تماس‌ها بررسی و تأیید کنید.</li></ol>"
    "<h2>تأیید</h2><p>یک تماس آزمایشی برقرار کنید و داخلی پاسخ‌دهنده یا دو طرف تماس داخلی را "
    "در جزئیات بررسی کنید.</p><h2>پیشگیری</h2><p>برای هر سازمان از یک سانترال استفاده کنید "
    "و پس از تغییر داخلی‌های سانترال، فهرست را دوباره همگام کنید.</p>"
)


def upgrade() -> None:
    op.add_column("tenants", sa.Column("pbx_host_uuid", sa.Uuid(), nullable=True))
    op.add_column("pbx_extensions", sa.Column("owner_linked_at", sa.DateTime(timezone=True)))
    op.add_column(
        "pbx_extensions",
        sa.Column("owner_managed", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    for column in _CALL_COLUMNS:
        op.add_column("calls", sa.Column(column, sa.Text(), nullable=True))
    op.add_column("call_operator_assignments", sa.Column("party_role", sa.Text(), nullable=True))

    bind = op.get_bind()
    bind.execute(
        sa.text(
            "INSERT INTO help_articles (slug, title, summary, body_html, body_plain, kind, "
            "status, position, published_at) VALUES (:slug, :title, :summary, :body, :summary, "
            "'article', 'published', 161, now())"
        ),
        {"slug": _ARTICLE, "title": _TITLE, "summary": _SUMMARY, "body": _BODY},
    )
    bind.execute(
        sa.text(
            "INSERT INTO help_error_codes "
            "(code, article_id, source, severity, title, quick_action) "
            "SELECT 'pbx_source_conflict', id, 'api', 'warning', :title, :action "
            "FROM help_articles WHERE slug = :slug"
        ),
        {
            "slug": _ARTICLE,
            "title": "منبع همگام‌سازی داخلی‌ها متفاوت است",
            "action": "اتصال سانترال را در صفحه داخلی‌ها بررسی کنید.",
        },
    )


def downgrade() -> None:
    op.execute("DELETE FROM help_error_codes WHERE code = 'pbx_source_conflict'")
    op.execute("DELETE FROM help_articles WHERE slug = 'pbx-operator-ownership'")
    op.drop_column("tenants", "pbx_host_uuid")
    op.drop_column("pbx_extensions", "owner_managed")
    op.drop_column("pbx_extensions", "owner_linked_at")
    op.drop_column("call_operator_assignments", "party_role")
    for column in reversed(_CALL_COLUMNS):
        op.drop_column("calls", column)
