"""Track deferred deletion of tenant audio and document storage usage."""

from alembic import op

revision = "0118_storage_deletions"
down_revision = "0117_meeting_attendees_help"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE TABLE audio_deletions (
        tenant_id uuid NOT NULL REFERENCES tenants(id),
        bucket text NOT NULL,
        object_key text NOT NULL,
        bytes bigint NOT NULL CHECK (bytes >= 0),
        attempts integer NOT NULL DEFAULT 0,
        due_at timestamptz NOT NULL DEFAULT now(),
        created_at timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (tenant_id, bucket, object_key)
    )""")
    op.execute("CREATE INDEX idx_audio_deletions_due ON audio_deletions (tenant_id, due_at)")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON audio_deletions TO cbi_app")
    op.execute("ALTER TABLE audio_deletions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audio_deletions FORCE ROW LEVEL SECURITY")
    op.execute("""CREATE POLICY audio_deletions_tenant_isolation ON audio_deletions
        USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
            OR current_setting('app.staff', true) = 'on')
        WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
            OR current_setting('app.staff', true) = 'on')""")
    op.execute(
        "CREATE INDEX idx_audio_objects_live_key "
        "ON audio_objects (tenant_id, bucket, object_key) WHERE deleted_at IS NULL"
    )
    op.execute("""INSERT INTO help_articles
        (slug, category_id, title, summary, body_html, body_plain,
         kind, status, position, published_at)
        SELECT 'organization-storage-usage', category_id, 'مصرف فضای سازمان',
        'مشاهدهٔ حجم فایل‌ها و زمان پاک‌سازی فضای صوت سازمان.',
        '<p>در تنظیمات حساب، بخش داده‌ها، حجم ثبت‌شدهٔ صدا، فایل‌های دستیار و بک‌آپ را ببینید. '
        'در پنل مدیریت، در صفحهٔ دیتابیس سازمان‌ها، گزارش فضای یک سازمان را باز کنید '
        'تا حجم فایل‌ها و پایگاه اختصاصی را بررسی کنید.</p>'
        '<p>پس از حذف یا انقضای صدا، دسترسی به فایل بسته می‌شود و پاک‌سازی در پس‌زمینه انجام می‌شود. '
        'اگر بک‌آپ در حال خواندن فایل باشد، پاک‌سازی تا پایان آن صبر می‌کند. '
        'حجم در انتظار پاک‌سازی را بعد از چند دقیقه دوباره بررسی کنید.</p>',
        'در بخش داده‌های تنظیمات حساب، حجم فایل‌های ثبت‌شده و صداهای در انتظار پاک‌سازی را بررسی کنید. '
        'مدیر سامانه می‌تواند گزارش فضای سازمان را در صفحهٔ دیتابیس سازمان‌ها باز کند.',
        'article', 'published', 24, now()
        FROM help_articles WHERE slug = 'organization-data-backup'
        ON CONFLICT (slug) DO NOTHING""")
    op.execute("""INSERT INTO help_error_codes
        (code, article_id, severity, title, quick_action, source)
        SELECT 'meeting_audio_storage_unavailable', id, 'error', 'صوت جلسه تأیید نشد',
        'وضعیت استوریج را در پنل مدیریت بررسی کنید و پس از رفع خطا دوباره تلاش کنید.', 'api'
        FROM help_articles WHERE slug = 'organization-storage-usage'
        ON CONFLICT (code) DO NOTHING""")


def downgrade() -> None:
    op.execute("DELETE FROM help_error_codes WHERE code = 'meeting_audio_storage_unavailable'")
    op.execute("DELETE FROM help_articles WHERE slug = 'organization-storage-usage'")
    op.execute("DROP INDEX idx_audio_objects_live_key")
    op.execute("DROP TABLE audio_deletions")
