"""Help article for assistant knowledge coverage and semantic search."""

import sqlalchemy as sa

from alembic import op

revision = "0077_assistant_knowledge_help_content"
down_revision = "0076_org_knowledge_chunks"
branch_labels = None
depends_on = None

ARTICLE_SLUG = "assistant-knowledge-coverage"
ARTICLE_TITLE = "دستیار چه اطلاعاتی از سازمان را می‌بیند"
ARTICLE_SUMMARY = "منابعی که دستیار در آن‌ها جست‌وجوی معنایی می‌کند و راه رفع ناقص بودن نتایج."


def _p(*parts: str) -> str:
    return "".join(parts)


ARTICLE_BODY = _p(
    "<h2>نشانه‌ها</h2><p>دستیار پاسخ می‌دهد «اطلاعاتی پیدا نشد» یا اعلام می‌کند جست‌وجوی "
    "معنایی در دسترس نیست، در حالی که می‌دانید داده وجود دارد.</p>",
    "<h2>علت</h2><p>دستیار هم آمار دقیق را از پایگاه داده می‌گیرد و هم در این منابع جست‌وجوی "
    "معنایی (برداری) می‌کند: خلاصهٔ تماس، متن مکالمه، حافظهٔ سازمان، تحلیل فروش، نتایج CRM، "
    "وظایف پیگیری، اهداف KPI، تیم‌ها، گزارش‌های زمان‌بندی‌شده و کوچینگ اپراتور. مخاطبین و "
    "گزارش‌ها فقط برای مدیر سازمان و اطلاعات مرتبط با تماس برای اپراتور فقط در تماس‌های خودش "
    "در دسترس است. تازه‌ترین داده‌ها پس از چند دقیقه ایندکس می‌شوند. اگر مدل «امبدینگ» عوض "
    "شود، تا پایان ایندکس مجدد نتایج ناقص‌اند. اگر سرویس امبدینگ خطا بدهد، دستیار فقط "
    "جست‌وجوی کلمه‌ای انجام می‌دهد و این را اعلام می‌کند.</p>",
    "<h2>رفع مشکل</h2><ol>"
    "<li>در پنل مدیریت، بخش پوشش دانش دستیار، تعداد «در انتظار» و «ناموفق» هر منبع را ببینید.</li>"
    "<li>اگر ناموفق زیاد است، تنظیمات سرویس امبدینگ (نشانی، کلید و مدل) را بررسی کنید.</li>"
    "<li>پس از تغییر مدل، منتظر پایان ایندکس مجدد بمانید؛ پیشرفت در همان بخش دیده می‌شود.</li>"
    "</ol>",
    "<h2>تأیید رفع مشکل</h2><p>در بخش پوشش دانش، «در انتظار» همهٔ منابع صفر شود و همان سؤال "
    "را دوباره از دستیار بپرسید.</p>",
    "<h2>پیشگیری</h2><p>پس از هر تغییر مدل یا سرویس امبدینگ، پوشش دانش را کنترل کنید. "
    "متن‌های بسیار طولانی تا ۱۰٬۰۰۰ بخش ایندکس می‌شوند.</p>",
)


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "INSERT INTO help_articles (slug, title, summary, body_html, body_plain, kind, "
            "status, position, published_at) VALUES (:slug, :title, :summary, :body, "
            ":summary, 'article', 'published', 141, now()) ON CONFLICT (slug) DO NOTHING"
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
