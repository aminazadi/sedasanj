"""Store call ASR overrides and revision identity, and publish rollout help."""

from html import escape

import sqlalchemy as sa

from alembic import op

revision = "0100_call_asr_rollout"
down_revision = "0099_jalase_negar_download_help"
branch_labels = None
depends_on = None

ARTICLES = (
    (
        "call-asr-silero",
        "تنظیم تشخیص گفتار تماس با مدل شنوا",
        None,
        "",
        (
            "در تنظیمات مدل پنل ادمین، حالت قطعه‌بندی گفتار جلسه‌نگار را انتخاب کنید. "
            "برای آزمون یک سازمان، حالت را فقط در تنظیمات همان سازمان تغییر دهید.",
            "مدل شنوا و Silero VAD را در AISERVICE نصب کنید. پروفایل تلفنی فقط زمانی "
            "به آستانه سفارشی نیاز دارد که روی نمونه تماس‌های واقعی آن را اندازه گرفته باشید.",
            "در جزئیات تماس، هویت موتور را در نسخه‌های متن بررسی کنید. "
            "برای بازگشت، مسیر استاندارد را برای همان سازمان یا کل سامانه انتخاب کنید.",
        ),
    ),
    (
        "error-asr-no-speech",
        "گفتار در فایل تماس تشخیص داده نشد",
        "asr_no_speech",
        "فایل تماس را پخش کنید و در صورت شنیدن گفت‌وگو، کد را به پشتیبانی بدهید.",
        (
            "پیاده‌سازی صدای تماس متوقف شده و کد asr_no_speech در جزئیات نمایش داده می‌شود.",
            "فایل ممکن است سکوت، موسیقی انتظار یا پیام IVR داشته باشد. گفتار ضعیف یا نویزی "
            "هم ممکن است از آستانه تشخیص عبور نکند.",
            "فایل را پخش کنید و در ضبط استریو هر دو کانال را بررسی کنید. اگر مکالمه شنیده "
            "می‌شود، شناسه تماس و کد خطا را به پشتیبانی بدهید تا ضبط و پروفایل بررسی شوند.",
            "پس از رفع مشکل، یک تماس آزمایشی را ضبط کنید و متن و زمان هر بخش را بررسی کنید. "
            "پیش از تغییر آستانه، تماس‌های مکالمه‌دار و تماس‌های بدون گفتار را جداگانه بسنجید.",
        ),
    ),
    (
        "error-call-asr-settings-invalid",
        "فهرست مدل‌های جایگزین تماس نامعتبر است",
        "call_asr_settings_invalid",
        "هر مدل جایگزین را یک بار از فهرست مدل‌های صوتی انتخاب کنید.",
        (
            "ذخیره تنظیمات پیاده‌سازی تماس با خطا روبه‌رو شده است.",
            "شناسه خالی، تکراری یا نامعتبر در فهرست مدل‌های جایگزین وجود دارد.",
            "مدل‌های قابل اجرا را از فهرست انتخاب کنید، موارد تکراری را بردارید و تنظیمات را "
            "دوباره ذخیره کنید. صفحه را تازه کنید و ترتیب ذخیره‌شده را بررسی کنید.",
        ),
    ),
    (
        "error-call-retranscription-busy",
        "تماس هنوز در حال پردازش است",
        "call_retranscription_busy",
        "پس از پایان پردازش یا اصلاح متن، دوباره رونویسی را درخواست کنید.",
        (
            "درخواست رونویسی دوباره پذیرفته نشده است.",
            "این تماس یک پردازش یا اصلاح متن فعال دارد. اجرای هم‌زمان ممکن است باعث شود "
            "نسخه اشتباه در پنل فعال شود.",
            "تا پایان پردازش صبر کنید و از جزئیات تماس دوباره رونویسی را بزنید. "
            "نسخه تازه را در فهرست نسخه‌های متن بررسی کنید.",
        ),
    ),
)


def upgrade() -> None:
    op.execute(
        "ALTER TABLE tenants ADD COLUMN call_asr_mode text NOT NULL DEFAULT 'inherit' "
        "CHECK (call_asr_mode IN ('inherit', 'legacy', 'vad_segment'))"
    )
    op.execute(
        "ALTER TABLE tenants ADD COLUMN call_asr_profile text NOT NULL DEFAULT 'inherit' "
        "CHECK (call_asr_profile IN ('inherit', 'jalase_negar', 'telephony'))"
    )
    op.execute("ALTER TABLE asr_transcript_revisions ADD COLUMN asr_identity text")
    bind = op.get_bind()
    for slug, title, code, action, paragraphs in ARTICLES:
        bind.execute(
            sa.text(
                "INSERT INTO help_articles "
                "(slug, title, summary, body_html, body_plain, kind, status, published_at) "
                "VALUES (:slug, :title, :summary, :html, :plain, :kind, 'published', now()) "
                "ON CONFLICT (slug) DO NOTHING"
            ),
            {
                "slug": slug,
                "title": title,
                "summary": paragraphs[0],
                "html": "".join(f"<p>{escape(paragraph)}</p>" for paragraph in paragraphs),
                "plain": "\n".join(paragraphs),
                "kind": "error" if code else "article",
            },
        )
        if code:
            bind.execute(
                sa.text(
                    "INSERT INTO help_error_codes "
                    "(code, article_id, source, severity, title, quick_action) "
                    "SELECT :code, id, 'api', 'warning', :title, :action FROM help_articles "
                    "WHERE slug = :slug ON CONFLICT (code) DO NOTHING"
                ),
                {"code": code, "slug": slug, "title": title, "action": action},
            )


def downgrade() -> None:
    bind = op.get_bind()
    for slug, _, code, _, _ in ARTICLES:
        if code:
            bind.execute(
                sa.text(
                    "DELETE FROM help_error_codes WHERE code = :code AND article_id = "
                    "(SELECT id FROM help_articles WHERE slug = :slug)"
                ),
                {"code": code, "slug": slug},
            )
        bind.execute(sa.text("DELETE FROM help_articles WHERE slug = :slug"), {"slug": slug})
    op.execute("ALTER TABLE asr_transcript_revisions DROP COLUMN asr_identity")
    op.execute("ALTER TABLE tenants DROP COLUMN call_asr_profile")
    op.execute("ALTER TABLE tenants DROP COLUMN call_asr_mode")
