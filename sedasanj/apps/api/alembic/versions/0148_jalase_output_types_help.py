"""Document the Jalase-Negar output types (conversion categories) in the help center."""

# ruff: noqa: E501 - Persian help prose is kept in complete paragraphs.

import sqlalchemy as sa

from alembic import op

revision = "0148_jalase_output_types_help"
down_revision = "0147_jalase_output_types"
branch_labels = None
depends_on = None

ARTICLES = (
    (
        "jalase-negar-output-types",
        "دسته‌های تبدیل جلسه‌نگار: ساخت، پیش‌نویس و انتشار",
        "ساخت دستهٔ تبدیل با تصویر، پرامپت و فیلد ورودی، انتشار نسخه‌ای و عیب‌یابی خطاهای دسته.",
        "<h2>نشانه‌ها</h2><p>ساخت، ویرایش یا انتشار یک دستهٔ تبدیل با یکی از خطاهای "
        '<code dir="ltr">output_type_invalid</code>، <code dir="ltr">output_type_code_taken</code>، '
        '<code dir="ltr">output_type_not_publishable</code> یا <code dir="ltr">output_type_builtin_locked</code> رد می‌شود.</p>'
        "<h2>علت</h2><p>هر دسته یک کد یکتای انگلیسی (حروف کوچک، عدد و _) دارد. نسخهٔ منتشرشده هرگز ویرایش نمی‌شود؛ "
        "هر تغییر یک پیش‌نویس جدید است که پس از انتشار جای نسخهٔ قبلی را می‌گیرد. برای انتشار، پرامپت اصلی باید پر باشد و در حالت «خلاصه‌سازی» "
        "دستور خلاصهٔ هر بخش هم لازم است. هر دسته حداکثر ۸ فیلد ورودی دارد و فیلد انتخابی دست‌کم دو گزینه می‌خواهد. "
        "دستهٔ «صورت‌جلسه» داخلی است: پرامپت آن در این بخش تغییر نمی‌کند و بایگانی نمی‌شود.</p>"
        "<h2>رفع مشکل</h2><ol><li>کد دسته را تغییر دهید یا کد تکراری را بایگانی‌شده بدانید و کد دیگری بگیرید.</li>"
        "<li>پرامپت اصلی (و برای خلاصه‌سازی دستور خلاصهٔ بخش) را بنویسید و دوباره منتشر کنید.</li>"
        "<li>تصویر دسته را فقط از کتابخانهٔ رسانهٔ راهنما و از نوع تصویر انتخاب کنید.</li>"
        "<li>برای تغییر یک دستهٔ منتشرشده، پیش‌نویس را ذخیره کنید و سپس منتشر کنید.</li></ol>"
        "<h2>تأیید رفع مشکل</h2><p>پس از انتشار، دسته در فهرست اپ جلسه‌نگار (کاربر واردشده) با تصویر و عنوان دیده می‌شود. نسخهٔ قبلی با وضعیت «جایگزین‌شده» در تاریخچه می‌ماند.</p>"
        "<h2>پیشگیری</h2><p>دسته‌های جدید را اول پیش‌نویس بسازید و با یک متن نمونه آزمایش کنید. پرامپت نباید نام، آیه یا عددی بسازد که در متن جلسه نیست.</p>",
        "output_type_invalid",
        "فیلدها و پرامپت دسته را طبق پیام خطا اصلاح کنید.",
    ),
)
EXTRA_CODES = (
    (
        "output_type_code_taken",
        "jalase-negar-output-types",
        "کد دسته تکراری است.",
        "کد دیگری برای دسته انتخاب کنید.",
    ),
    (
        "output_type_not_publishable",
        "jalase-negar-output-types",
        "پیش‌نویس آمادهٔ انتشار نیست.",
        "پرامپت اصلی و دستور خلاصهٔ بخش را کامل کنید.",
    ),
    (
        "output_type_builtin_locked",
        "jalase-negar-output-types",
        "دستهٔ داخلی قابل تغییر نیست.",
        "فقط عنوان، توضیح و تصویر دستهٔ داخلی را تغییر دهید.",
    ),
    (
        "output_type_not_found",
        "jalase-negar-output-types",
        "دستهٔ تبدیل پیدا نشد.",
        "فهرست دسته‌ها را تازه کنید.",
    ),
)


def upgrade() -> None:
    bind = op.get_bind()
    for position, (slug, title, summary, body, code, action) in enumerate(ARTICLES, start=153):
        bind.execute(
            sa.text(
                "INSERT INTO help_articles (slug,title,summary,body_html,body_plain,kind,status,"
                "position,published_at) "
                "VALUES (:slug,:title,:summary,:body,:summary,'article','published',:position,now()) "
                "ON CONFLICT (slug) DO NOTHING"
            ),
            {"slug": slug, "title": title, "summary": summary, "body": body, "position": position},
        )
        bind.execute(
            sa.text(
                "INSERT INTO help_error_codes (code,source,severity,article_id,title,quick_action) "
                "SELECT :code,'api','error',id,:summary,:action "
                "FROM help_articles WHERE slug=:slug ON CONFLICT (code) DO NOTHING"
            ),
            {"slug": slug, "code": code, "summary": summary, "action": action},
        )
    for code, slug, summary, action in EXTRA_CODES:
        bind.execute(
            sa.text(
                "INSERT INTO help_error_codes (code,source,severity,article_id,title,quick_action) "
                "SELECT :code,'api','error',id,:summary,:action "
                "FROM help_articles WHERE slug=:slug ON CONFLICT (code) DO NOTHING"
            ),
            {"slug": slug, "code": code, "summary": summary, "action": action},
        )


def downgrade() -> None:
    bind = op.get_bind()
    codes = [row[4] for row in ARTICLES] + [row[0] for row in EXTRA_CODES]
    for code in codes:
        bind.execute(sa.text("DELETE FROM help_error_codes WHERE code=:code"), {"code": code})
    for slug, *_ in ARTICLES:
        bind.execute(sa.text("DELETE FROM help_articles WHERE slug=:slug"), {"slug": slug})
