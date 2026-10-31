"""Help article for the KPI and team settings tab."""

import sqlalchemy as sa

from alembic import op

revision = "0086_kpi_settings_help_content"
down_revision = "0085_webhook_help_content"
branch_labels = None
depends_on = None

ARTICLE_SLUG = "kpi-settings-guide"
ARTICLE_TITLE = "راهنمای تنظیمات KPI و تیم‌ها"
ARTICLE_SUMMARY = "هر آستانه، مرحلهٔ قیف و ویجت داشبورد چه اثری دارد و چرا ثبت تنظیمات رد می‌شود."


def _p(*parts: str) -> str:
    return "".join(parts)


ARTICLE_BODY = _p(
    "<h2>نشانه‌ها</h2><p>در «تنظیمات حساب» برگهٔ «KPI و تیم‌ها» ثبت تنظیمات با پیام خطا رد "
    "می‌شود یا پس از ثبت، داشبورد مطابق انتظار تغییر نمی‌کند.</p>",
    "<h2>علت</h2><ul>"
    "<li>آستانهٔ فرصت داغ کمتر از اطمینان فرصت محتمل است.</li>"
    "<li>SLA پیگیری بیرون از ۱ تا ۷۲۰ ساعت یا حداقل نمونه بیرون از ۱ تا ۱۰۰۰ است.</li>"
    "<li>taxonomy اعتراض‌ها خالی است یا مقدار تکراری دارد.</li>"
    "<li>مقدار هدف بیشتر از ۱۰۰ است؛ هر سه معیار هدف (نرخ تبدیل، امتیاز کیفیت، پیگیری در SLA) "
    "درصد یا امتیاز از ۱۰۰ هستند.</li>"
    "<li>برای همان معیار و دامنه، هدفی با بازهٔ زمانی هم‌پوشان وجود دارد.</li></ul>",
    "<h2>رفع مشکل</h2><ol>"
    "<li>مقدارهای هشداردار را در حد مجاز اصلاح و دوباره «ثبت نسخه جدید» را بزنید.</li>"
    "<li>مراحل «تماس مؤثر»، «واجد شرایط»، «فروش» و «باخت» ضروری‌اند؛ فقط «علاقه‌مند»، "
    "«پیگیری» و «پیشنهاد» را می‌توان خاموش کرد.</li>"
    '<li>مقدارهای taxonomy اعتراض‌ها را انگلیسی و یکتا بنویسید و <code dir="ltr">other</code> '
    "را نگه دارید، چون اعتراض خارج از فهرست به آن نگاشت می‌شود.</li>"
    "<li>اگر اپراتورها نباید هدف تیم را ببینند، «نمایش هدف تیم به اپراتور» را خاموش کنید؛ "
    "آن‌ها فقط هدف‌های سازمان را می‌بینند.</li></ol>",
    "<h2>تأیید رفع مشکل</h2><p>پس از ثبت، شمارهٔ نسخه بالای صفحه یکی زیاد می‌شود. "
    "داشبورد را باز کنید: ویجت‌های خاموش دیده نمی‌شوند و مراحل قیف مطابق انتخاب شماست.</p>",
    "<h2>پیشگیری</h2><p>نسخهٔ taxonomy با تغییر مراحل قیف یا فهرست اعتراض‌ها خودکار یکی بالا "
    "می‌رود و تماس‌های قبلی با نسخهٔ پیشین نگه داشته می‌شوند؛ تحلیل دوبارهٔ آن‌ها نسخهٔ جدید "
    "را می‌گیرد. تغییر آستانه‌ها فقط محاسبهٔ داشبورد را عوض می‌کند و تماس‌ها دوباره تحلیل "
    "نمی‌شوند.</p>",
)


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "INSERT INTO help_articles (slug, title, summary, body_html, body_plain, kind, "
            "status, position, published_at) VALUES (:slug, :title, :summary, :body, "
            ":summary, 'article', 'published', 150, now()) ON CONFLICT (slug) DO NOTHING"
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
