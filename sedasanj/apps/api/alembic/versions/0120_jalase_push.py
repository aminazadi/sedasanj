"""Register Jalase-Negar push installations, campaigns and help."""

from alembic import op

revision = "0120_jalase_push"
down_revision = "0119_gzip_backup_help"
branch_labels = None
depends_on = None

TABLES = (
    "jalase_push_settings",
    "jalase_push_installations",
    "jalase_push_campaigns",
    "jalase_push_deliveries",
)


def upgrade() -> None:
    op.execute("""
        CREATE TABLE jalase_push_settings (
            id integer PRIMARY KEY CHECK (id = 1),
            enabled boolean NOT NULL,
            project text NOT NULL,
            credentials text
        )
    """)
    op.execute("""
        CREATE TABLE jalase_push_installations (
            id uuid PRIMARY KEY,
            secret_hash text NOT NULL,
            token_hash text NOT NULL UNIQUE,
            token text NOT NULL,
            mobile_key_id uuid REFERENCES api_keys(id) ON DELETE SET NULL,
            version text NOT NULL,
            channel text NOT NULL,
            enabled boolean NOT NULL,
            invalidated boolean NOT NULL DEFAULT false,
            seen_at timestamptz NOT NULL
        )
    """)
    op.create_index(
        "ix_jalase_push_installations_mobile_key_id", "jalase_push_installations", ["mobile_key_id"]
    )
    op.execute("""
        CREATE TABLE jalase_push_campaigns (
            id uuid PRIMARY KEY,
            actor_id uuid NOT NULL,
            payload jsonb NOT NULL,
            scheduled_at timestamptz NOT NULL,
            expires_at timestamptz NOT NULL,
            started_at timestamptz,
            cancelled_at timestamptz
        )
    """)
    op.create_index(
        "ix_jalase_push_campaigns_scheduled_at", "jalase_push_campaigns", ["scheduled_at"]
    )
    op.execute("""
        CREATE TABLE jalase_push_deliveries (
            campaign_id uuid NOT NULL REFERENCES jalase_push_campaigns(id) ON DELETE CASCADE,
            installation_id uuid NOT NULL,
            state text NOT NULL,
            next_at timestamptz NOT NULL,
            attempts integer NOT NULL,
            error text,
            PRIMARY KEY (campaign_id, installation_id)
        )
    """)
    op.create_index(
        "ix_jalase_push_deliveries_ready", "jalase_push_deliveries", ["state", "next_at"]
    )
    for table in TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO cbi_app")
    op.execute("""
        INSERT INTO help_articles
            (slug, category_id, title, summary, body_html, body_plain,
             kind, status, position, published_at)
        SELECT 'jalase-negar-push', category_id, 'ارسال پوش جلسه‌نگار',
            'تنظیم Firebase، آزمون دستگاه و پیگیری ارسال.',
            '<p>در پنل اصلی، پروژه و اعتبارنامهٔ Firebase را در تنظیمات پوش ذخیره کنید. '
            'آزمون اتصال را اجرا کنید، نسخهٔ جدید اپ را باز کنید و مجوز اعلان بدهید. '
            'پیش از ارسال عمومی، یک دستگاه را در فرم ارسال آزمایشی انتخاب کنید.</p>'
            '<p>اگر دستگاه در فهرست دیده نمی‌شود، اتصال اینترنت و تنظیم پوش دستگاه را '
            'بررسی کنید و اپ را دوباره باز کنید. برای خطای پیام، فیلدها و اندازهٔ داده را '
            'بررسی کنید. برای خطای سرویس، پروژه و دسترسی حساب Firebase را بررسی کنید.</p>'
            '<p>پذیرش Firebase در تاریخچه یعنی سرویس پیام را پذیرفته است. '
            'برای تأیید نمایش، اعلان را روی دستگاه آزمایشی باز کنید.</p>',
            'پروژه و اعتبارنامه را بررسی کنید و پوش را روی یک دستگاه آزمایش کنید.',
            'article', 'published', 40, now()
        FROM help_articles WHERE slug = 'jalase-negar-android-install'
        ON CONFLICT (slug) DO NOTHING
    """)
    op.execute("""
        INSERT INTO help_error_codes (code, article_id, severity, title, quick_action, source)
        SELECT item.code, article.id, 'error', item.title, item.action, 'api'
        FROM help_articles AS article CROSS JOIN (VALUES
            ('jalase_push_invalid', 'پیام پوش نامعتبر است',
             'ورودی فرم و اندازهٔ پیام را بررسی کنید.'),
            ('jalase_push_unavailable', 'سرویس پوش در دسترس نیست',
             'تنظیمات Firebase را آزمایش کنید.'),
            ('jalase_push_token_expired', 'شناسهٔ پوش دستگاه منقضی شد',
             'اپ را دوباره باز کنید تا شناسهٔ پوش تازه شود.'),
            ('jalase_push_installation', 'ثبت دستگاه تأیید نشد',
             'اپ را دوباره باز و اتصال را بررسی کنید.')
        ) AS item(code, title, action)
        WHERE article.slug = 'jalase-negar-push'
        ON CONFLICT (code) DO NOTHING
    """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM help_error_codes
        WHERE code IN ('jalase_push_invalid', 'jalase_push_unavailable',
            'jalase_push_installation', 'jalase_push_token_expired')
    """)
    op.execute("DELETE FROM help_articles WHERE slug = 'jalase-negar-push'")
    for table in reversed(TABLES):
        op.drop_table(table)
