"""Help for deleting a meeting and for abandoned uploads."""

# ruff: noqa: E501 - Persian help prose is kept in complete paragraphs.

import sqlalchemy as sa

from alembic import op

revision = "0162_jalase_meeting_delete_help"
down_revision = "0161_jalase_rewards_events"
branch_labels = None
depends_on = None

SLUG = "jalase-negar-delete-meeting"
CODE = "ingest_abandoned"
TITLE = "حذف جلسه و آزاد شدن اعتبار"
SUMMARY = "حذف جلسه از گوشی و سرور، لغو جلسهٔ نیمه‌کاره و آزاد شدن اعتبار رزروشده."
BODY = (
    "<h2>حذف جلسه</h2><p>وقتی جلسه‌ای از حساب شخصی را در جلسه‌نگار حذف می‌کنید، فایل صوتی، متن، صورت‌جلسه و اسناد آن از گوشی و از سرور صداسنج پاک می‌شوند. اگر هنگام حذف اینترنت قطع باشد، درخواست حذف در صف می‌ماند و با برگشت اینترنت دوباره فرستاده می‌شود. جلسه‌ای که به سازمان فرستاده شده در پنل سازمان مدیریت می‌شود و حذف آن از گوشی نسخهٔ سازمان را پاک نمی‌کند.</p>"
    "<h2>جلسهٔ نیمه‌کاره</h2><p>اگر ارسال جلسه‌ای نیمه‌کاره بماند و چند ساعت خبری از گوشی نرسد، سرور آن را لغو می‌کند و اعتباری که برایش رزرو شده بود آزاد می‌شود. جلسهٔ لغوشده در فهرست با خطا نشان داده می‌شود و در شمارش نشان‌ها حساب نمی‌شود.</p>"
    '<h2>خطا</h2><p><code dir="ltr">ingest_abandoned</code>: جلسه پیش از پایان ارسال، رها شده و سرور آن را لغو کرده است.</p>'
    "<h2>رفع مشکل</h2><ol><li>اینترنت گوشی را بررسی کنید و جلسه را دوباره ضبط کنید.</li>"
    "<li>اگر فایل صوتی روی گوشی مانده، از دکمهٔ «ارسال به صداسنج» دوباره بفرستید.</li>"
    "<li>اعتبار آزادشده را در «پلن و مصرف» ببینید.</li></ol>"
    "<h2>حساب شخصی</h2><p>حساب شخصی جلسه‌نگار فقط با ساعت و توکن هوش مصنوعی حساب می‌شود؛ بستهٔ ساعت از «پلن و مصرف» خریداری می‌شود. نشان‌ها هنگام کامل شدن جلسه یا سند داده می‌شوند و برای دیدن هدیه لازم نیست صفحهٔ پیشرفت را باز نگه دارید.</p>"
    "<h2>تأیید</h2><p>پس از حذف، جلسه از فهرست گوشی و از پنل صداسنج خارج می‌شود و اعتبار رزروشده در مصرف ماه دیده نمی‌شود.</p>"
)


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "INSERT INTO help_articles (slug,title,summary,body_html,body_plain,kind,status,"
            "position,published_at) "
            "VALUES (:slug,:title,:summary,:body,:summary,'article','published',162,now()) "
            "ON CONFLICT (slug) DO NOTHING"
        ),
        {"slug": SLUG, "title": TITLE, "summary": SUMMARY, "body": BODY},
    )
    bind.execute(
        sa.text(
            "INSERT INTO help_error_codes (code,source,severity,article_id,title,quick_action) "
            "SELECT :code,'worker','warning',id,:title,:action "
            "FROM help_articles WHERE slug=:slug ON CONFLICT (code) DO NOTHING"
        ),
        {
            "slug": SLUG,
            "code": CODE,
            "title": "جلسهٔ نیمه‌کاره لغو شد و اعتبارش آزاد شد.",
            "action": "اینترنت را بررسی کنید و جلسه را دوباره ضبط و ارسال کنید.",
        },
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM help_error_codes WHERE code=:code"), {"code": CODE})
    bind.execute(sa.text("DELETE FROM help_articles WHERE slug=:slug"), {"slug": SLUG})
