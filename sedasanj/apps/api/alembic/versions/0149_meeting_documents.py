"""Documents made from a meeting transcript by an output type (counseling, lecture notes, ...)."""

# ruff: noqa: E501 - Persian help prose is kept in complete paragraphs.

import sqlalchemy as sa

from alembic import op

revision = "0149_meeting_documents"
down_revision = "0148_jalase_output_types_help"
branch_labels = None
depends_on = None

POLICY = """USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
            OR current_setting('app.staff', true) = 'on')
        WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
            OR current_setting('app.staff', true) = 'on')"""

SLUG = "jalase-negar-documents"
TITLE = "اسناد جلسه‌نگار: ساخت، ویرایش و عیب‌یابی"
SUMMARY = "ساخت سند از متن جلسه در دستهٔ دلخواه، ویرایش نسخه‌ای و رفع خطاهای ساخت سند."
BODY = (
    "<h2>نشانه‌ها</h2><p>ساخت سند با یکی از خطاهای "
    '<code dir="ltr">document_input_invalid</code>، <code dir="ltr">document_not_found</code> یا '
    '<code dir="ltr">document_generation_failed</code> متوقف می‌شود، یا سند در وضعیت «ناموفق» می‌ماند.</p>'
    "<h2>علت</h2><p>هر جلسه برای هر دسته یک سند دارد و هر ساخت یا ویرایش یک نسخهٔ جدید است؛ نسخه‌های قبلی پاک نمی‌شوند. "
    "فیلدهای ورودی دسته باید با تعریف ادمین بخوانند (اجباری بودن، حداکثر طول و گزینه‌های مجاز). "
    "اگر مدل زبانی پاسخ نامعتبر بدهد، یک بار دوباره امتحان می‌شود و در صورت تکرار، سند ناموفق می‌شود و جلسه و صورت‌جلسه دست نمی‌خورند.</p>"
    "<h2>رفع مشکل</h2><ol><li>فیلدهای ورودی را طبق پیام خطا اصلاح کنید.</li>"
    "<li>برای سند ناموفق «ساخت دوباره» را بزنید؛ نسخهٔ قبلی سالم می‌ماند.</li>"
    "<li>اگر خطا ادامه داشت، در ادمین مدل و کلید ارائه‌دهندهٔ «صورت‌جلسهٔ جلسات» را بررسی کنید.</li></ol>"
    "<h2>تأیید رفع مشکل</h2><p>وضعیت سند «آماده» می‌شود و متن در تب سند دیده می‌شود.</p>"
    "<h2>پیشگیری</h2><p>پیش از انتشار یک دسته، آن را روی یک متن نمونه آزمایش کنید.</p>"
)
CODES = (
    (
        "document_input_invalid",
        "ورودی سند معتبر نیست.",
        "فیلدهای ورودی دسته را طبق پیام خطا اصلاح کنید.",
    ),
    ("document_not_found", "سند پیدا نشد.", "فهرست اسناد جلسه را تازه کنید."),
    (
        "document_generation_failed",
        "ساخت سند ناموفق بود.",
        "«ساخت دوباره» را بزنید؛ اگر ادامه داشت مدل جلسات را در ادمین بررسی کنید.",
    ),
)


def upgrade() -> None:
    op.execute("""CREATE TABLE meeting_documents (
        id uuid NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
        tenant_id uuid NOT NULL REFERENCES tenants(id),
        meeting_id uuid NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
        output_type_code varchar(40) NOT NULL,
        output_type_version integer NOT NULL CHECK (output_type_version >= 1),
        input_values jsonb NOT NULL DEFAULT '{}'::jsonb,
        user_note text NOT NULL DEFAULT '' CHECK (char_length(user_note) <= 500),
        status varchar(16) NOT NULL DEFAULT 'queued'
            CHECK (status IN ('queued','running','done','failed')),
        error_code varchar(64),
        progress_pct integer NOT NULL DEFAULT 0 CHECK (progress_pct BETWEEN 0 AND 100),
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        UNIQUE (meeting_id, output_type_code)
    )""")
    op.execute("""CREATE TABLE meeting_document_versions (
        tenant_id uuid NOT NULL REFERENCES tenants(id),
        document_id uuid NOT NULL REFERENCES meeting_documents(id) ON DELETE CASCADE,
        version integer NOT NULL CHECK (version >= 1),
        markdown text NOT NULL,
        structured jsonb,
        source varchar(16) NOT NULL CHECK (source IN ('model','user_edit')),
        model text,
        provider text,
        prompt_sha256 text,
        is_selected boolean NOT NULL DEFAULT false,
        created_at timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (document_id, version)
    )""")
    op.execute(
        "CREATE INDEX idx_meeting_documents_tenant ON meeting_documents (tenant_id, meeting_id)"
    )
    op.execute(
        "CREATE INDEX idx_meeting_documents_pending ON meeting_documents (updated_at) "
        "WHERE status IN ('queued','running')"
    )
    op.execute(
        "CREATE INDEX idx_meeting_document_versions_tenant ON meeting_document_versions (tenant_id)"
    )
    for table in ("meeting_documents", "meeting_document_versions"):
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO cbi_app")
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY {table}_tenant_isolation ON {table} {POLICY}")
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "INSERT INTO help_articles (slug,title,summary,body_html,body_plain,kind,status,"
            "position,published_at) "
            "VALUES (:slug,:title,:summary,:body,:summary,'article','published',154,now()) "
            "ON CONFLICT (slug) DO NOTHING"
        ),
        {"slug": SLUG, "title": TITLE, "summary": SUMMARY, "body": BODY},
    )
    for code, summary, action in CODES:
        bind.execute(
            sa.text(
                "INSERT INTO help_error_codes (code,source,severity,article_id,title,quick_action) "
                "SELECT :code,'api','error',id,:summary,:action "
                "FROM help_articles WHERE slug=:slug ON CONFLICT (code) DO NOTHING"
            ),
            {"slug": SLUG, "code": code, "summary": summary, "action": action},
        )


def downgrade() -> None:
    bind = op.get_bind()
    for code, _summary, _action in CODES:
        bind.execute(sa.text("DELETE FROM help_error_codes WHERE code=:code"), {"code": code})
    bind.execute(sa.text("DELETE FROM help_articles WHERE slug=:slug"), {"slug": SLUG})
    op.execute("DROP TABLE IF EXISTS meeting_document_versions")
    op.execute("DROP TABLE IF EXISTS meeting_documents")
