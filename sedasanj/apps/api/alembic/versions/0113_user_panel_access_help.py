"""Add per-user panel sections and the access-denied help article."""

# ruff: noqa: E501 - Persian help prose is kept in complete paragraphs.

import sqlalchemy as sa

from alembic import op

revision = "0113_user_panel_access_help"
down_revision = "0112_user_panel_permissions"
branch_labels = None
depends_on = None

TITLE = "تعیین دسترسی کاربر به بخش‌های پنل"
BODY = """<h2>نشانه‌ها</h2>
<p>بخشی از منو دیده نمی‌شود یا خطای panel_access_denied نمایش داده می‌شود.</p>
<h2>علت</h2><p>مدیر سازمان دسترسی آن بخش را برای حساب فعال نکرده است. نقش کاربر به‌تنهایی به معنی دسترسی به همه بخش‌ها نیست.</p>
<h2>رفع مشکل</h2><ol><li>از مدیر سازمان بخواهید به تنظیمات حساب، کاربران و ویرایش کاربر برود.</li>
<li>در «دسترسی به بخش‌های پنل» بخش‌های لازم را انتخاب و ذخیره کند. برای بازگشت به دسترسی معمول نقش، «پیش‌فرض نقش» را بزند.</li>
<li>مدیر فقط دسترسی‌هایی را می‌تواند واگذار کند که خودش دارد. تغییر نقش یا دسترسی خودتان باید توسط مدیر سازمان دیگری انجام شود.</li></ol>
<h2>بررسی نتیجه</h2><p>پنل را تازه کنید؛ منو و تب‌های مجاز نمایش داده می‌شوند. محدودیت سمت سرور از درخواست بعدی اعمال می‌شود و واردکردن مستقیم آدرس هم آن را دور نمی‌زند.</p>
<h2>پیشگیری</h2><p>فقط بخش‌های لازم را فعال کنید. انتخاب بخش، محدودیت عملیات نقش یا تماس‌های مجاز اپراتور را تغییر نمی‌دهد. پروفایل و راهنما همیشه در دسترس‌اند. تماس‌ها و پیام‌های صوتی یک دسترسی مشترک دارند.</p>"""


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "INSERT INTO help_articles (slug, title, summary, body_html, body_plain, kind, status, published_at) "
            "VALUES ('user-panel-access', :title, :summary, :body, :plain, 'article', 'published', now()) "
            "ON CONFLICT (slug) DO NOTHING"
        ),
        {
            "title": TITLE,
            "summary": "انتخاب دسترسی هر کاربر به بخش‌های پنل و رفع خطای دسترسی.",
            "body": BODY,
            "plain": TITLE + " panel_access_denied",
        },
    )
    bind.execute(
        sa.text(
            "INSERT INTO help_error_codes (code, article_id, source, severity, title, quick_action) "
            "SELECT 'panel_access_denied', id, 'api', 'warning', :title, :action "
            "FROM help_articles WHERE slug = 'user-panel-access' ON CONFLICT (code) DO NOTHING"
        ),
        {
            "title": "دسترسی بخش فعال نیست",
            "action": "از مدیر سازمان بخواهید دسترسی این بخش را فعال کند.",
        },
    )


def downgrade() -> None:
    op.execute("DELETE FROM help_error_codes WHERE code = 'panel_access_denied'")
    op.execute("DELETE FROM help_articles WHERE slug = 'user-panel-access'")
