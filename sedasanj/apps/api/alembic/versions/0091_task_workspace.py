"""Task ownership, workflow, immutable activity and workspace help."""

import sqlalchemy as sa

from alembic import op

revision = "0091_task_workspace"
down_revision = "0090_table_pagination_help_content"
branch_labels = None
depends_on = None

ARTICLE_SLUG = "task-workspace-guide"
ARTICLE_TITLE = "مدیریت و پیگیری کارهای تماس"
ARTICLE_BODY = (
    "<h2>میز پیگیری</h2><p>کارها از تحلیل تماس یا با ثبت دستی روی تماس مشتری ساخته می‌شوند. "
    "برای ساخت دستی، تماس مجاز را انتخاب کنید و عنوان را بنویسید. مسئول اولیه تعیین نشده است.</p>"
    "<h2>فهرست و فیلترها</h2><p>امروز شامل کارهای ناتمام بدون موعد و سررسیدشده است. "
    "عقب‌افتاده فقط موعدهای گذشته را نشان می‌دهد. تاریخ‌ها با منطقه زمانی سازمان محاسبه می‌شوند. "
    "جست‌وجو، مسئول، اولویت، وضعیت و بازه موعد در سرور اعمال می‌شوند. تنظیمات فهرست و "
    "کار انتخابی در آدرس ذخیره می‌شوند و صفحه‌بندی برای فهرست و تاریخچه مستقل است.</p>"
    "<h2>مسئول و دسترسی</h2><p>مدیر سازمان می‌تواند کار را به مدیران سازمان یا اپراتورهای "
    "دارای دسترسی جاری به تماس واگذار کند. واگذاری دسترسی تازه ایجاد نمی‌کند. اگر انتساب "
    "تماس تغییر کرد، مدیر باید هشدار مسئول فاقد دسترسی را بررسی و مسئول تازه انتخاب کند.</p>"
    "<h2>پیگیری</h2><p>وضعیت‌ها باز، در حال انجام و انجام‌شده هستند. یادداشت‌های پیگیری "
    "و تغییرات با زمان و عامل در تاریخچه ثبت می‌شوند. یادداشت ثبت‌شده قابل حذف یا ویرایش نیست. "
    "بازگرداندن کار انجام‌شده، زمان تکمیل قبلی را پاک می‌کند و در تاریخچه ثبت می‌شود.</p>"
    "<h2>نشانه‌ها</h2><p>ذخیره انجام نمی‌شود یا مسئول انتخاب‌شده پذیرفته نمی‌شود.</p>"
    "<h2>علت</h2><p>نسخه کار تغییر کرده یا شخص انتخاب‌شده دیگر به تماس دسترسی ندارد.</p>"
    '<h2>رفع مشکل</h2><ol><li>برای خطای <code dir="ltr">task_version_conflict</code> '
    "دریافت نسخه تازه را بزنید، تغییرات جدید را بررسی و ویرایش خود را دوباره ثبت کنید.</li>"
    '<li>برای خطای <code dir="ltr">task_assignee_invalid</code> فهرست افراد را تازه کنید '
    "و شخصی با دسترسی جاری به تماس انتخاب کنید.</li></ol>"
    "<h2>تأیید رفع مشکل</h2><p>نسخه و آخرین تغییر کار باید تازه شود و رویداد ثبت‌شده در "
    "تاریخچه دیده شود.</p><h2>پیشگیری</h2><p>پیش از ویرایش طولانی، نسخه تازه را دریافت کنید "
    "و پس از تغییر انتساب تماس‌ها، مسئول کارهای باز را بازبینی کنید.</p>"
)


def upgrade() -> None:
    op.execute("ALTER TABLE follow_up_tasks DROP CONSTRAINT follow_up_tasks_status_check")
    op.execute(
        "ALTER TABLE follow_up_tasks ADD CONSTRAINT follow_up_tasks_status_check "
        "CHECK (status IN ('open','in_progress','done'))"
    )
    op.execute(
        "ALTER TABLE follow_up_tasks ADD COLUMN assignee_id uuid "
        "REFERENCES users(id) ON DELETE SET NULL"
    )
    op.execute(
        "ALTER TABLE follow_up_tasks ADD COLUMN origin text NOT NULL DEFAULT 'analysis' "
        "CHECK (origin IN ('analysis','manual'))"
    )
    op.execute(
        "ALTER TABLE follow_up_tasks ADD COLUMN version integer NOT NULL DEFAULT 1 "
        "CHECK (version >= 1)"
    )
    op.execute(
        "CREATE INDEX idx_tasks_assignee ON follow_up_tasks "
        "(tenant_id, assignee_id, status, due_date, id)"
    )
    op.execute("CREATE INDEX idx_tasks_updated ON follow_up_tasks (tenant_id, updated_at, id)")
    op.execute("""CREATE TABLE follow_up_task_events (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id uuid NOT NULL REFERENCES tenants(id),
        task_id uuid NOT NULL REFERENCES follow_up_tasks(id) ON DELETE CASCADE,
        actor_id uuid REFERENCES users(id) ON DELETE SET NULL,
        kind text NOT NULL CHECK (kind IN ('created','updated','note')),
        changes jsonb NOT NULL DEFAULT '{}'::jsonb,
        note text,
        created_at timestamptz NOT NULL DEFAULT now()
    )""")
    op.execute(
        "CREATE INDEX idx_task_events_task ON follow_up_task_events "
        "(tenant_id, task_id, created_at, id)"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON follow_up_task_events TO cbi_app")
    op.execute("ALTER TABLE follow_up_task_events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE follow_up_task_events FORCE ROW LEVEL SECURITY")
    op.execute("""CREATE POLICY task_events_tenant_isolation ON follow_up_task_events
        USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
            OR current_setting('app.staff', true) = 'on')
        WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
            OR current_setting('app.staff', true) = 'on')""")
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "INSERT INTO help_articles (slug,title,summary,body_html,body_plain,"
            "kind,status,position,"
            "published_at) VALUES (:slug,:title,:title,:body,:title,"
            "'article','published',152,now()) "
            "ON CONFLICT (slug) DO NOTHING"
        ),
        {"slug": ARTICLE_SLUG, "title": ARTICLE_TITLE, "body": ARTICLE_BODY},
    )
    for code in ("task_version_conflict", "task_assignee_invalid"):
        bind.execute(
            sa.text(
                "INSERT INTO help_error_codes (code,article_id,source,severity,title,"
                "quick_action) SELECT :code,id,'api','warning',:summary,:action "
                "FROM help_articles WHERE slug=:slug ON CONFLICT (code) DO NOTHING"
            ),
            {
                "code": code,
                "slug": ARTICLE_SLUG,
                "summary": "نسخه یا مسئول کار نیاز به بررسی دارد",
                "action": "نسخه تازه کار و فهرست افراد مجاز را دریافت و دوباره تلاش کنید.",
            },
        )


def downgrade() -> None:
    op.execute(
        "DELETE FROM help_error_codes WHERE code IN "
        "('task_version_conflict','task_assignee_invalid')"
    )
    op.get_bind().execute(
        sa.text("DELETE FROM help_articles WHERE slug=:slug"), {"slug": ARTICLE_SLUG}
    )
    op.execute("DROP TABLE follow_up_task_events")
    op.execute("DROP INDEX idx_tasks_updated")
    op.execute("DROP INDEX idx_tasks_assignee")
    op.execute("ALTER TABLE follow_up_tasks DROP COLUMN version")
    op.execute("ALTER TABLE follow_up_tasks DROP COLUMN origin")
    op.execute("ALTER TABLE follow_up_tasks DROP COLUMN assignee_id")
    op.execute("UPDATE follow_up_tasks SET status='open' WHERE status='in_progress'")
    op.execute("ALTER TABLE follow_up_tasks DROP CONSTRAINT follow_up_tasks_status_check")
    op.execute(
        "ALTER TABLE follow_up_tasks ADD CONSTRAINT follow_up_tasks_status_check "
        "CHECK (status IN ('open','done'))"
    )
