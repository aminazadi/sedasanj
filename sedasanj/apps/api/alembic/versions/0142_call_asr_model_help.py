"""Document the admin-selected call ASR model (Shenava or Whisper) in the help center."""

# ruff: noqa: E501 - the article text is long Persian prose that does not wrap usefully

from html import escape

import sqlalchemy as sa

from alembic import op

revision = "0142_call_asr_model_help"
down_revision = "0141_tenant_database_help"
branch_labels = None
depends_on = None

# slug -> (previous paragraphs written by 0100_call_asr_rollout, new paragraphs)
SILERO_SLUG = "call-asr-silero"
SETTINGS_SLUG = "error-call-asr-settings-invalid"

SILERO_OLD = (
    "در تنظیمات مدل پنل ادمین، حالت قطعه‌بندی گفتار جلسه‌نگار را انتخاب کنید. "
    "برای آزمون یک سازمان، حالت را فقط در تنظیمات همان سازمان تغییر دهید.",
    "مدل شنوا و Silero VAD را در AISERVICE نصب کنید. پروفایل تلفنی فقط زمانی "
    "به آستانه سفارشی نیاز دارد که روی نمونه تماس‌های واقعی آن را اندازه گرفته باشید.",
    "در جزئیات تماس، هویت موتور را در نسخه‌های متن بررسی کنید. "
    "برای بازگشت، مسیر استاندارد را برای همان سازمان یا کل سامانه انتخاب کنید.",
)
SILERO_NEW = (
    SILERO_OLD[0],
    "در همان بخش، «مدل تبدیل صدای تماس در حالت جلسه‌نگار» را انتخاب کنید. مدل‌های شنوا (Shenava) "
    "و Whisper (از جمله Whisper Persian v4 و BuzzASR) پشتیبانی می‌شوند. اگر خالی بماند، "
    "همان «مدل ASR» عمومی به‌تنهایی اجرا می‌شود؛ شنوا یا هر مدل دیگری فقط وقتی جایگزین است که "
    "خودتان در فهرست «مدل‌های جایگزین» اضافه کرده باشید.",
    "مدل انتخابی و Silero VAD را در AISERVICE نصب کنید. با Whisper هم گفتار با همان مرز‌های "
    "Silero بخش‌بندی و هر بخش جدا رونویسی می‌شود؛ مدل‌های Whisper بزرگ ممکن است روی پردازندهٔ معمولی کند باشند "
    "(سرعت‌شان را اندازه نگرفته‌ایم)، پس پیش از انتخاب برای کل سازمان‌ها، سرعت و دقت را روی چند تماس واقعی بسنجید. "
    "پروفایل تلفنی فقط زمانی به آستانه سفارشی نیاز دارد که روی نمونه تماس‌های واقعی آن را "
    "اندازه گرفته باشید.",
    SILERO_OLD[2] + " شناسهٔ مدل واقعی اجراشده در هویت موتور هر نسخهٔ متن ثبت می‌شود؛ اگر مدل انتخابی "
    "در دسترس نباشد و جایگزین تعریف کرده باشید، تماس به آن می‌رود.",
)

SETTINGS_OLD = (
    "ذخیره تنظیمات پیاده‌سازی تماس با خطا روبه‌رو شده است.",
    "شناسه خالی، تکراری یا نامعتبر در فهرست مدل‌های جایگزین وجود دارد.",
    "مدل‌های قابل اجرا را از فهرست انتخاب کنید، موارد تکراری را بردارید و تنظیمات را "
    "دوباره ذخیره کنید. صفحه را تازه کنید و ترتیب ذخیره‌شده را بررسی کنید.",
)
SETTINGS_NEW = (
    SETTINGS_OLD[0],
    "شناسه خالی، تکراری یا نامعتبر در فهرست مدل‌های جایگزین وجود دارد، یا شناسهٔ «مدل تبدیل "
    "صدای تماس» فاصله دارد.",
    SETTINGS_OLD[2]
    + " «مدل تبدیل صدای تماس» را هم از فهرست مدل‌های AISERVICE انتخاب کنید، نه با تایپ دستی.",
)


def _set(bind: sa.Connection, slug: str, paragraphs: tuple[str, ...]) -> None:
    bind.execute(
        sa.text(
            "UPDATE help_articles SET summary = :summary, body_html = :html, "
            "body_plain = :plain WHERE slug = :slug"
        ),
        {
            "slug": slug,
            "summary": paragraphs[0],
            "html": "".join(f"<p>{escape(paragraph)}</p>" for paragraph in paragraphs),
            "plain": "\n".join(paragraphs),
        },
    )


def upgrade() -> None:
    bind = op.get_bind()
    _set(bind, SILERO_SLUG, SILERO_NEW)
    _set(bind, SETTINGS_SLUG, SETTINGS_NEW)


def downgrade() -> None:
    bind = op.get_bind()
    _set(bind, SILERO_SLUG, SILERO_OLD)
    _set(bind, SETTINGS_SLUG, SETTINGS_OLD)
