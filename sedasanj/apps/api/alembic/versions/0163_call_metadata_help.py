"""Help for calls whose caller/dialed numbers could not be resolved."""

# ruff: noqa: E501 - Persian help prose is kept in complete paragraphs.

import sqlalchemy as sa

from alembic import op

revision = "0163_call_metadata_help"
down_revision = "0162_jalase_meeting_delete_help"
branch_labels = None
depends_on = None

SLUG = "call-metadata-missing"
CODES = ("SS-UPL-1001", "SS-UPL-1004")
TITLE = "ارسال نشدن تماس به پنل: شمارهٔ تماس‌گیرنده یا مقصد مشخص نیست"
SUMMARY = (
    "ضبط تماس ساخته شده اما شمارهٔ تماس‌گیرنده یا مقصد آن از dialplan و CDR خوانده نشده "
    "و سرور تماس را رد می‌کند."
)
BODY = (
    '<h2>نشانه</h2><p>در صفحهٔ ماژول یا فایل <code dir="ltr">/var/log/asterisk-recording-uploader/uploader.log</code> '
    'یکی از این کدها دیده می‌شود: <code dir="ltr">SS-UPL-0422</code> با پیام '
    '<code dir="ltr">caller_number and dialed_number are required</code>، '
    '<code dir="ltr">SS-UPL-1004</code> یا <code dir="ltr">SS-UPL-1001</code>. '
    'فایل ضبط در پوشهٔ <code dir="ltr">failed/</code> باقی می‌ماند و در پنل ثبت نمی‌شود.</p>'
    '<h2>علت</h2><p>در برخی مسیرهای FreePBX مقدار <code dir="ltr">CDR(dnid)</code> یا '
    '<code dir="ltr">CDR(dst)</code> هنگام اجرای hook یک برچسب dialplan است (مثلاً '
    '<code dir="ltr">recordcheck</code>)، نه شماره. ماژول این برچسب را به‌عنوان مقصد ارسال '
    "نمی‌کند؛ به‌جای آن تلاش می‌کند داخلی پاسخ‌دهنده یا شمارهٔ واقعی را از CDR بخواند. "
    "اگر ردیف CDR دیر نهایی شود یا دسترسی CDR برقرار نباشد، شماره‌ها موقتاً نامشخص می‌مانند و "
    'API درخواست را با <code dir="ltr">422</code> رد می‌کند.</p>'
    "<h2>رفع مشکل</h2><ol>"
    "<li>ماژول را به نسخهٔ 1.5.6 یا بالاتر ارتقا دهید.</li>"
    '<li>روی PBX بررسی کنید که CDR فعال است و جدول <code dir="ltr">cdr</code> برای تماس آزمایشی '
    'ردیف دارد؛ تنظیم <code dir="ltr">unanswered=yes</code> در <code dir="ltr">cdr.conf</code> '
    "برای تماس‌های بی‌پاسخ لازم است.</li>"
    "<li>یک تماس آزمایشی پاسخ‌داده‌شده بگیرید و ثبت آن را در پنل ببینید.</li>"
    "<li>برای فایل‌های قبلی ابتدا فهرست را ببینید:</li></ol>"
    '<pre dir="ltr">php /usr/local/bin/asterisk-recording-uploader/bin/recover-unresolved.php --dry-run</pre>'
    "<p>اگر مقصد قابل تعیین بود، اجرای واقعی:</p>"
    '<pre dir="ltr">php /usr/local/bin/asterisk-recording-uploader/bin/recover-unresolved.php</pre>'
    "<p>فقط تماس‌هایی بازگردانده می‌شوند که شماره‌شان با اطمینان از CDR یا DID خوانده شود؛ "
    'بقیه با کد <code dir="ltr">SS-SWP-1001</code> در <code dir="ltr">failed/</code> می‌مانند. '
    'هیچ فایلی حذف نمی‌شود. پیش از اجرا از پوشهٔ <code dir="ltr">failed/</code> نسخهٔ پشتیبان بگیرید.</p>'
    "<h2>تأیید</h2><p>شمارهٔ تماس‌گیرنده و مقصد در پنل با تماس آزمایشی یکسان باشد و فایل مربوطه "
    'از <code dir="ltr">failed/</code> خارج شده باشد. اگر CDR برای یک تماس چند پاسخ‌دهندهٔ '
    'متفاوت نشان دهد، ماژول حدس نمی‌زند و تماس در <code dir="ltr">failed/</code> می‌ماند.</p>'
    "<h2>پیشگیری</h2><p>پس از هر تغییر در dialplan یا callrecording یک تماس آزمایشی بگیرید و "
    "وضعیت صف و لاگ را بررسی کنید. اجرای دوره‌ای "
    '<code dir="ltr">recover-unresolved.php --dry-run</code> با cron می‌تواند تماس‌های '
    "دیرنهایی‌شده را زودتر برگرداند.</p>"
)


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "INSERT INTO help_articles (slug,title,summary,body_html,body_plain,kind,status,"
            "position,published_at) "
            "VALUES (:slug,:title,:summary,:body,:summary,'article','published',163,now()) "
            "ON CONFLICT (slug) DO NOTHING"
        ),
        {"slug": SLUG, "title": TITLE, "summary": SUMMARY, "body": BODY},
    )
    bind.execute(
        sa.text(
            "INSERT INTO help_error_codes (code,source,severity,article_id,title,quick_action) "
            "SELECT :code,'module',:severity,id,:title,:action "
            "FROM help_articles WHERE slug=:slug "
            "ON CONFLICT (code) DO UPDATE SET source='module', severity=EXCLUDED.severity, "
            "article_id=EXCLUDED.article_id, title=EXCLUDED.title, quick_action=EXCLUDED.quick_action"
        ),
        {
            "slug": SLUG,
            "code": "SS-UPL-1001",
            "severity": "error",
            "title": "شمارهٔ تماس‌گیرنده یا مقصد در فرادادهٔ تماس موجود نیست.",
            "action": "CDR و dialplan را بررسی کنید و پس از اصلاح، recover-unresolved.php را اجرا کنید.",
        },
    )
    bind.execute(
        sa.text(
            "INSERT INTO help_error_codes (code,source,severity,article_id,title,quick_action) "
            "SELECT :code,'module',:severity,id,:title,:action "
            "FROM help_articles WHERE slug=:slug "
            "ON CONFLICT (code) DO UPDATE SET source='module', severity=EXCLUDED.severity, "
            "article_id=EXCLUDED.article_id, title=EXCLUDED.title, quick_action=EXCLUDED.quick_action"
        ),
        {
            "slug": SLUG,
            "code": "SS-UPL-1004",
            "severity": "error",
            "title": "شماره‌های تماس هنوز از CDR مشخص نشده‌اند؛ ماژول دوباره تلاش می‌کند.",
            "action": "وضعیت CDR را بررسی کنید؛ پس از تکمیل CDR، recover-unresolved.php را اجرا کنید.",
        },
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "DELETE FROM help_error_codes WHERE code IN ('SS-UPL-1001','SS-UPL-1004') "
            "AND article_id = (SELECT id FROM help_articles WHERE slug=:slug)"
        ),
        {"slug": SLUG},
    )
    bind.execute(sa.text("DELETE FROM help_articles WHERE slug=:slug"), {"slug": SLUG})
