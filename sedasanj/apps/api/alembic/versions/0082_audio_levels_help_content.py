"""Help article for the audio preparation settings and adaptive per-channel level matching."""

# ruff: noqa: E501 - the article text is long Persian prose that does not wrap usefully

import sqlalchemy as sa

from alembic import op

revision = "0082_audio_levels_help_content"
down_revision = "0081_api_key_help_content"
branch_labels = None
depends_on = None

ARTICLE_SLUG = "audio-preprocessing-guide"
ARTICLE_TITLE = "راهنمای آماده‌سازی صوت و یکسان‌سازی بلندی دو طرف مکالمه"
ARTICLE_SUMMARY = "چرا صدای مشتری ضعیف‌تر از اپراتور ضبط می‌شود، مدل «وضوح گفتار تلفنی — تطبیقی» چه می‌کند و چطور تنظیمش کنید."


def _p(*parts: str) -> str:
    return "".join(parts)


ARTICLE_BODY = _p(
    "<h2>نشانه‌ها</h2><p>در موج صدای تماس، صدای اپراتور پرانرژی و صدای مشتری بسیار کم‌دامنه است. "
    "متن مشتری ناقص، پر از خطا یا خالی می‌شود؛ چون مدل تبدیل گفتار به متن صدای ضعیف را «سکوت» یا "
    "نویز می‌بیند.</p>",
    "<h2>علت</h2><ul>"
    "<li>صدای مشتری از خط بیرونی و گوشی او می‌آید و معمولاً ده‌ها دسی‌بل ضعیف‌تر از اپراتور "
    "ضبط می‌شود.</li>"
    "<li>هر طرف مکالمه در یک کانال جدا ضبط می‌شود، اما پیش‌فرض هیچ تقویتی روی کانال ضعیف "
    "اعمال نمی‌شود.</li>"
    "<li>کدک فشرده‌ی ترانک (مثل G.729) یا حذف اکوی گوشی نیز سطح صدا را کم می‌کند و این تنظیمات "
    "در خود مرکز تلفن هستند، نه در پنل.</li></ul>",
    "<h2>رفع مشکل</h2><ol>"
    "<li>در «تنظیمات» برگهٔ «صوت» کلید «آماده‌سازی صوت» را روشن کنید.</li>"
    '<li>«مدل بهبود کیفیت» را روی <code dir="ltr">speech-telephony-adaptive</code> '
    "(وضوح گفتار تلفنی — تطبیقی) بگذارید. این مدل بلندی هر کانال را جداگانه اندازه می‌گیرد و "
    "تا سطح هدف بالا می‌برد.</li>"
    '<li>«بلندی هدف» را روی <code dir="ltr">-20</code> LUFS نگه دارید. «حداکثر تقویت» پیش‌فرض '
    '<code dir="ltr">30</code> دسی‌بل است؛ برای خطوط بسیار پرنویز کمترش کنید.</li>'
    "<li>مدل حذف نویز را «بدون حذف نویز» یا «متعادل» بگذارید؛ حذف نویز قوی جزئیات گفتار را "
    "کم می‌کند.</li>"
    "<li>ثبت کنید. فقط تماس‌های جدید و تبدیل دوبارهٔ تماس‌های قبلی از تنظیم تازه استفاده می‌کنند.</li>"
    "</ol>",
    "<h2>تأیید رفع مشکل</h2><p>یک تماس نمونه را دوباره به متن تبدیل کنید و متن مشتری را با قبل "
    "مقایسه کنید. لاگ سرویس تبدیل گفتار برای هر کانال یک خط «asr channel level matched» با "
    '<code dir="ltr">measured_lufs</code> و <code dir="ltr">gain_db</code> دارد؛ '
    "کانال ضعیف باید گین مثبت بزرگ‌تری بگیرد.</p>",
    "<h2>نکته‌ها و پیشگیری</h2><ul>"
    "<li>کانالی که بلندی‌اش از ۵۵- LUFS کمتر باشد «ساکت» حساب می‌شود و تقویت نمی‌شود، تا نویز خط "
    "بلند نشود و مدل متن ساختگی تولید نکند.</li>"
    '<li>اگر خطای <code dir="ltr">asr_preprocessing_failed</code> دیدید، ابتدا مطمئن شوید '
    "ffmpeg روی سرور کار می‌کند و فایل صوتی سالم است.</li>"
    "<li>اگر تماس‌ها با کدک G.729 یا با حذف اکوی تهاجمی ضبط می‌شوند، کیفیت از مبدأ پایین است. "
    "کدک ترانک را به alaw یا ulaw تغییر دهید؛ این تغییر در مرکز تلفن انجام می‌شود و ⚠ باید روی "
    "آزمایشگاه شما تأیید شود.</li></ul>",
)


def upgrade() -> None:
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
