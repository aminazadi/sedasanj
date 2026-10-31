"""Help articles for the AI operator coach."""

import html

import sqlalchemy as sa

from alembic import op

revision = "0073_operator_coach_help_content"
down_revision = "0072_operator_call_coachings"
branch_labels = None
depends_on = None

ARTICLE_SLUG = "operator-coach-guide"
ERROR_SLUG = "error-coach-unavailable"
ERROR_CODE = "coach_unavailable"


def _p(*parts: str) -> str:
    return "".join(parts)


GUIDE_BODY = _p(
    "<h2>نشانه‌ها</h2><p>در صفحهٔ جزئیات تماس، بعد از «کارهای قابل پیگیری»، بخش «مربی ارتباط با "
    "مشتری» نمایش داده می‌شود. اگر بخش خالی است یا پیام «ناموفق» می‌بینید، این راهنما را دنبال "
    "کنید.</p>",
    "<h2>علت</h2><p>مربی بعد از تحلیل هر تماس پاسخ‌داده‌شده اجرا می‌شود. تماس‌های کوتاه، بدون صدای "
    "اپراتور یا بدون متن آماده، عمداً بررسی نمی‌شوند. اگر مدیر سیستم مربی را غیرفعال کرده باشد "
    "یا مدل/مسیر آن تنظیم نشده باشد، نتیجه‌ای تولید نمی‌شود.</p>",
    "<h2>رفع مشکل</h2><ol>"
    "<li>اگر وضعیت «در حال تحلیل» است چند دقیقه صبر کنید.</li>"
    "<li>اگر «ناموفق» است، روی «تحلیل دوباره» بزنید.</li>"
    "<li>مدیر سیستم: در تنظیمات ادمین، بخش «مدل‌ها و مسیرها»، مربی را فعال و مسیر (سرویس AI یا "
    "9Router) و مدل را انتخاب کند؛ پرامپت در برگهٔ «پرامپت‌ها» ویرایش می‌شود.</li></ol>",
    "<h2>تأیید رفع مشکل</h2><p>پس از تحلیل دوباره، خلاصه، مشکلات همراه با نقل‌قول و جمله‌های "
    "پیشنهادی نمایش داده می‌شود.</p>",
    "<h2>پیشگیری</h2><p>مدل را از فهرست مدل‌های همان مسیر انتخاب کنید و پس از ویرایش پرامپت، "
    "نتیجه را روی چند تماس واقعی بررسی کنید. اپراتورها فقط تماس‌های خودشان و مدیر سازمان همهٔ "
    "تماس‌ها را می‌بیند.</p>",
)

ERROR_ACTION = "مربی غیرفعال است یا هنوز تحلیل تماس تمام نشده؛ بعد از پایان تحلیل دوباره تلاش کنید."


def upgrade() -> None:
    bind = op.get_bind()
    articles = (
        (
            ARTICLE_SLUG,
            "راهنمای مربی ارتباط با مشتری",
            "article",
            "راهنمای استفاده و رفع مشکل.",
            GUIDE_BODY,
            130,
        ),
        (
            ERROR_SLUG,
            "مربی ارتباط با مشتری در دسترس نیست",
            "error",
            ERROR_ACTION,
            "<h2>نشانه‌ها</h2><p>"
            + html.escape(ERROR_ACTION)
            + "</p><h2>علت</h2><p>مربی در تنظیمات غیرفعال است یا تحلیل تماس هنوز کامل نشده است.</p>"
            "<h2>رفع مشکل</h2><ol><li>چند دقیقه صبر کنید و دوباره تلاش کنید.</li>"
            "<li>از مدیر سیستم بخواهید مربی را در تنظیمات ادمین فعال کند.</li></ol>"
            "<h2>تأیید رفع مشکل</h2><p>دکمهٔ «تحلیل دوباره» پیام «در صف» را برمی‌گرداند.</p>"
            "<h2>پیشگیری</h2><p>مربی را فقط پس از انتخاب مسیر و مدل معتبر فعال نگه دارید.</p>",
            131,
        ),
    )
    for slug, title, kind, summary, body, position in articles:
        bind.execute(
            sa.text(
                "INSERT INTO help_articles (slug, title, summary, body_html, body_plain, kind, "
                "status, position, published_at) VALUES (:slug, :title, :summary, :body, "
                ":summary, :kind, 'published', :position, now()) ON CONFLICT (slug) DO NOTHING"
            ),
            {
                "slug": slug,
                "title": title,
                "summary": summary,
                "body": body,
                "kind": kind,
                "position": position,
            },
        )
    bind.execute(
        sa.text(
            "INSERT INTO help_error_codes (code, article_id, source, severity, title, "
            "quick_action) SELECT :code, id, 'api', 'warning', :title, :action "
            "FROM help_articles WHERE slug = :slug ON CONFLICT (code) DO NOTHING"
        ),
        {
            "code": ERROR_CODE,
            "slug": ERROR_SLUG,
            "title": "مربی ارتباط با مشتری در دسترس نیست",
            "action": ERROR_ACTION,
        },
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM help_error_codes WHERE code = :code"), {"code": ERROR_CODE})
    for slug in (ARTICLE_SLUG, ERROR_SLUG):
        bind.execute(sa.text("DELETE FROM help_articles WHERE slug = :slug"), {"slug": slug})
