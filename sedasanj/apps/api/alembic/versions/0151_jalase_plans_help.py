"""Help articles for Jalase-Negar plans, usage shown as hours, and token packs."""

# ruff: noqa: E501 - Persian help prose is kept in complete paragraphs.

import sqlalchemy as sa

from alembic import op

revision = "0151_jalase_plans_help"
down_revision = "0150_jalase_plans_tokens"
branch_labels = None
depends_on = None

ARTICLES = (
    (
        "jalase-negar-plans-and-usage",
        "پلن‌ها و مصرف جلسه‌نگار: ساعت باقی‌مانده و خرید توکن",
        "مصرف جلسه‌نگار چگونه حساب می‌شود، چرا به‌صورت ساعت نشان داده می‌شود و پس از اتمام چه باید کرد.",
        "<h2>مصرف چگونه حساب می‌شود</h2><p>هر پلن هر ماه مقداری استفادهٔ رایگان دارد، حتی پلن رایگان. مصرف از روی توکن‌های واقعی گزارش‌شده توسط مدل هوش مصنوعی کم می‌شود، نه با تخمین. برای خواناتر شدن، اپ آن را به‌صورت «حدود N ساعت جلسه» نشان می‌دهد.</p>"
        "<p>ترتیب مصرف: ابتدا سهمیهٔ ماهانهٔ پلن، سپس توکن‌های خریداری‌شده یا هدیه. سهمیهٔ ماهانه با شروع دورهٔ جدید دوباره شارژ می‌شود؛ توکن خریداری‌شده شارژ مجدد نمی‌شود و تا زمان مصرف می‌ماند.</p>"
        "<h2>وقتی ساعت‌ها تمام شد</h2><ol><li>در اپ، بخش «پلن و مصرف» را باز کنید.</li>"
        "<li>برای ادامهٔ فوری، یک بستهٔ توکن بخرید یا پلن را ارتقا دهید.</li>"
        "<li>اگر ارتقا نمی‌دهید، تا شروع دورهٔ بعد صبر کنید؛ تاریخ شارژ مجدد در همان صفحه نوشته شده است.</li></ol>"
        "<h2>پایان ماه پلن پولی</h2><p>اشتراک پولی یک‌ماهه است. پس از پایان ماه (و مهلت تمدید)، حساب شما به پلن رایگان برمی‌گردد و اسنادتان حفظ می‌شود. برای ادامهٔ پلن پولی دوباره پرداخت کنید؛ تمدید زودهنگام، ماه جدید را به پایان دورهٔ جاری اضافه می‌کند.</p>"
        "<h2>برای مدیر سیستم</h2><p>قیمت پلن‌ها، سهمیهٔ ماهانهٔ توکن و بسته‌های توکن از ادمین ویرایش می‌شوند: «پلن‌ها و نسخه‌ها» (فیلتر محصول جلسه‌نگار) و «بسته‌های توکن». نسخهٔ منتشرشده تغییر نمی‌کند؛ نسخهٔ جدید بسازید و منتشر کنید. مشترکان فعلی تا تمدید بعدی روی نسخهٔ خودشان می‌مانند. ضریب «توکن معادل یک ساعت» در تنظیمات مدل‌ها فقط نمایش را عوض می‌کند.</p>"
        "<p>مقدارهای اولیهٔ سهمیه و ضریب تخمینی‌اند. پس از چند هفته، میانگین توکن یک ساعت جلسه را از گزارش مصرف بخوانید و ضریب و سهمیه‌ها را اصلاح کنید.</p>"
        "<h2>تأیید رفع مشکل</h2><p>پس از خرید بسته، ساعت باقی‌مانده در اپ بیشتر می‌شود و سفارش در وضعیت «پرداخت‌شده» است.</p>",
    ),
)


def upgrade() -> None:
    bind = op.get_bind()
    for position, (slug, title, summary, body) in enumerate(ARTICLES, start=154):
        bind.execute(
            sa.text(
                "INSERT INTO help_articles (slug,title,summary,body_html,body_plain,kind,status,"
                "position,published_at) "
                "VALUES (:slug,:title,:summary,:body,:summary,'article','published',:position,now()) "
                "ON CONFLICT (slug) DO NOTHING"
            ),
            {"slug": slug, "title": title, "summary": summary, "body": body, "position": position},
        )


def downgrade() -> None:
    bind = op.get_bind()
    for slug, *_ in ARTICLES:
        bind.execute(sa.text("DELETE FROM help_articles WHERE slug=:slug"), {"slug": slug})
