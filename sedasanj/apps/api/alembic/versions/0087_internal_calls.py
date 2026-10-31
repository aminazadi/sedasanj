"""Internal (extension-to-extension) calls: direction check, backfill and help article."""

import sqlalchemy as sa

from alembic import op

revision = "0087_internal_calls"
down_revision = "0086_kpi_settings_help_content"
branch_labels = None
depends_on = None

ARTICLE_SLUG = "internal-calls-guide"
ARTICLE_TITLE = "تماس داخلی بین همکاران"
ARTICLE_SUMMARY = (
    "تماس بین دو داخلی چگونه شناخته می‌شود و در داشبورد، مربی و گزارش‌ها چه رفتاری دارد."
)
ARTICLE_BODY = (
    "<h2>نشانه‌ها</h2><p>تماس بین دو همکار در آمار مشتری حساب شده یا مربی دربارهٔ آن "
    "مثل تماس مشتری نظر داده است.</p>"
    "<h2>علت</h2><p>تماسی «داخلی» شناخته می‌شود که شمارهٔ تماس‌گیرنده و شمارهٔ مقصد هر دو در "
    "فهرست داخلی‌های همگام‌شده از ماژول باشند. اگر فهرست همگام نشده باشد یا داخلی غیرفعال باشد، "
    "تماس ورودی/خروجی ثبت می‌شود.</p>"
    "<h2>رفع مشکل</h2><ol><li>در ماژول FreePBX دکمهٔ «همگام‌سازی داخلی‌ها» را بزنید.</li>"
    "<li>پس از همگام‌سازی، تماس‌های ۳۰ روز اخیر خودکار دوباره دسته‌بندی می‌شوند.</li></ol>"
    "<h2>رفتار سامانه</h2><ul>"
    "<li>تماس داخلی در معیارهای مشتری (نرخ پاسخ، تبدیل، قیف، SLA، امتیاز اپراتور) نمی‌آید؛ "
    "برای شمارش آن‌ها «تماس‌های داخلی را در KPI حساب کن» را در تنظیمات KPI روشن کنید.</li>"
    "<li>خلاصه و پیشنهادهای مربی بر پایهٔ همکاری با همکار نوشته می‌شود، نه برخورد با مشتری.</li>"
    "<li>برای تماس داخلی وظیفهٔ پیگیری مشتری ساخته نمی‌شود.</li></ul>"
    "<h2>تأیید</h2><p>در فهرست تماس‌ها فیلتر «داخلی» را انتخاب کنید.</p>"
)

_BACKFILL = (
    "UPDATE calls c SET direction = 'internal', "
    "agent_extension = COALESCE(c.agent_extension, c.dialed_number) "
    "WHERE (c.direction IS NULL OR c.direction <> 'internal') "
    "AND EXISTS (SELECT 1 FROM pbx_extensions e WHERE e.tenant_id = c.tenant_id "
    "AND e.active AND e.extension = c.caller_number) "
    "AND EXISTS (SELECT 1 FROM pbx_extensions e WHERE e.tenant_id = c.tenant_id "
    "AND e.active AND e.extension = c.dialed_number)"
)


def upgrade() -> None:
    op.execute(_BACKFILL)
    op.execute(
        "ALTER TABLE calls ADD CONSTRAINT calls_direction_check "
        "CHECK (direction IS NULL OR direction IN ('inbound','outbound','internal')) NOT VALID"
    )
    op.get_bind().execute(
        sa.text(
            "INSERT INTO help_articles (slug, title, summary, body_html, body_plain, kind, "
            "status, position, published_at) VALUES (:slug, :title, :summary, :body, "
            ":summary, 'article', 'published', 160, now()) ON CONFLICT (slug) DO NOTHING"
        ),
        {
            "slug": ARTICLE_SLUG,
            "title": ARTICLE_TITLE,
            "summary": ARTICLE_SUMMARY,
            "body": ARTICLE_BODY,
        },
    )


def downgrade() -> None:
    op.get_bind().execute(
        sa.text("DELETE FROM help_articles WHERE slug = :slug"), {"slug": ARTICLE_SLUG}
    )
    op.execute("ALTER TABLE calls DROP CONSTRAINT IF EXISTS calls_direction_check")
