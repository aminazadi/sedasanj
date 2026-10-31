"""Document combined prompt and organization rubric coaching dimensions."""

import sqlalchemy as sa

from alembic import op

revision = "0075_coach_rubric_help"
down_revision = "0074_executive_dashboard_help_content"
branch_labels = None
depends_on = None

SUPPLEMENT = (
    "<h2>منبع معیارهای مربی</h2><p>مربی هم معیارهای پرامپت و هم معیارهای فعال امتیازدهی "
    "اپراتور سازمان را بررسی می‌کند. عنوان، توضیح، وزن و پنج سطح هر معیار سازمان به مدل "
    "داده می‌شود. اگر سازمان معیار اختصاصی ندارد، معیارهای پیش‌فرض امتیازدهی استفاده می‌شوند. "
    "امتیاز هر معیار سازمان با تکیه بر سطوح آن از صفر تا صد تعیین می‌شود؛ وزن، اولویت معیار "
    "است و در امتیاز همان کارت ضرب نمی‌شود. امتیاز کلی مربی میانگین کارت‌های دارای امتیاز "
    "است و با امتیاز رسمی و وزنی اپراتور تفاوت دارد. خط تیره یعنی امتیاز قابل اتکا در دسترس "
    "نیست.</p><p>معیارهای سازمان را در تنظیمات امتیازدهی اپراتور و راهنمای مربی را در تنظیمات "
    "ادمین، برگهٔ پرامپت‌ها ویرایش کنید. پس از تغییر، برای گزارش‌های قبلی «تحلیل دوباره» مربی "
    "را اجرا کنید و حضور معیارها را در تفصیل تحلیل بررسی کنید.</p>"
)


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "UPDATE help_articles SET body_html = body_html || :supplement "
            "WHERE slug = :slug AND position(:supplement in body_html) = 0"
        ),
        {"supplement": SUPPLEMENT, "slug": "operator-coach-guide"},
    )


def downgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "UPDATE help_articles SET body_html = replace(body_html, :supplement, '') "
            "WHERE slug = :slug"
        ),
        {"supplement": SUPPLEMENT, "slug": "operator-coach-guide"},
    )
