"""Document downloading and restoring portable organization backups."""

from alembic import op

revision = "0119_gzip_backup_help"
down_revision = "0118_storage_deletions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        INSERT INTO help_articles
            (slug, category_id, title, summary, body_html, body_plain,
             kind, status, position, published_at)
        SELECT 'organization-gzip-backup', category_id,
            'دانلود و بازیابی بک‌آپ فشردهٔ سازمان',
            'بازیابی فایل‌های gzip و آرشیوهای قبلی با کلید بازیابی و پیش‌نمایش داده‌ها.',
            '<p>فایل جدید با پسوند <bdi>.gzip</bdi> دانلود می‌شود. خود فایل را در بخش '
            'بازیابی انتخاب کنید و کلید زمان ساخت بک‌آپ را وارد کنید. فایل‌های قبلی '
            '<bdi>.sedasanj</bdi> را هم می‌توانید مستقیم بارگذاری کنید.</p>'
            '<p>پس از بارگذاری، پیش‌نمایش و نگاشت اعضا را بررسی و عملیات را تأیید کنید. '
            'در صورت خطای <bdi>org_archive_invalid</bdi>، کلید را بررسی و فایل را '
            'دوباره از منبع اصلی دانلود کنید.</p>'
            '<p>فهرست حاضران و نام گویندگان همراه جلسه منتقل می‌شود. پروفایل خصوصی و '
            'اثر صوتی گوینده در بک‌آپ عملیاتی محافظت می‌شود. وضعیت و شمار ردیف‌های '
            'بازیابی‌شده را در تاریخچهٔ داده‌ها بررسی کنید.</p>',
            'فایل .gzip یا .sedasanj را مستقیم بارگذاری کنید، کلید بازیابی را وارد کنید '
            'و پیش از تأیید، پیش‌نمایش و نگاشت اعضا را بررسی کنید.',
            'article', 'published', 25, now()
        FROM help_articles WHERE slug = 'organization-data-backup'
        ON CONFLICT (slug) DO NOTHING
        """)


def downgrade() -> None:
    op.execute("DELETE FROM help_articles WHERE slug = 'organization-gzip-backup'")
