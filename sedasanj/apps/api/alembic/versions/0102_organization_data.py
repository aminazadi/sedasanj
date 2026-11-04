"""Add organization archive settings, durable runs, receipts, and recovery help."""

from html import escape

import sqlalchemy as sa

from alembic import op

revision = "0102_organization_data"
down_revision = "0101_report_documents"
branch_labels = None
depends_on = None

GUIDE = (
    "بک‌آپ و بازیابی داده‌های سازمان",
    "در تنظیمات حساب، تب داده‌ها را باز کنید و کلید بازیابی را جدا از فایل بک‌آپ نگه دارید. "
    "برای ورود، فایل باینری و کلید همان بک‌آپ را انتخاب کنید، نگاشت اعضا و تعداد موارد را "
    "بررسی کنید و سپس ورود را تأیید کنید. برای بک‌آپ دوره‌ای، مقصد را تست و زمان اجرا را ثبت کنید.",
)
ERRORS = {
    "org_archive_invalid": (
        "فایل یا کلید بازیابی معتبر نیست",
        "فایل اصلی و کلید متناظر را دوباره انتخاب کنید. "
        "فایل را تغییر ندهید و پیش‌نمایش را بررسی کنید.",
        False,
    ),
    "org_archive_too_large": (
        "حجم بک‌آپ بیش از حد مجاز است",
        "اندازه فایل را بررسی کنید و برای افزایش سقف مجاز با مدیر سامانه هماهنگ کنید.",
        False,
    ),
    "org_archive_mapping": (
        "عضو مقصد در نگاشت معتبر نیست",
        "فهرست اعضای مقصد را تازه کنید، عضو موجود را انتخاب کنید و پیش‌نمایش را دوباره بسازید.",
        False,
    ),
    "org_archive_review_changed": (
        "پیش‌نمایش بازیابی نیاز به بررسی دوباره دارد",
        "داده‌های مقصد تغییر کرده‌اند. پیش‌نمایش تازه را بررسی و دوباره تأیید کنید.",
        False,
    ),
    "org_archive_unavailable": (
        "ساخت یا بازیابی بک‌آپ انجام نشد",
        "وضعیت ذخیره‌سازی و کلید اسرار پلتفرم را با مدیر سامانه بررسی و دوباره تلاش کنید.",
        True,
    ),
    "org_backup_destination": (
        "مقصد بک‌آپ مجاز نیست",
        "میزبان عمومی، مسیر و پروتکل را اصلاح کنید و تست اتصال را دوباره اجرا کنید.",
        False,
    ),
    "org_backup_ftp_failed": (
        "ارسال بک‌آپ به سرور فایل ناموفق بود",
        "مسیر، مجوز نوشتن، شبکه و گواهی FTPS را بررسی کنید. سپس تست اتصال را اجرا کنید.",
        True,
    ),
}


def _error_slug(code: str) -> str:
    return "error-" + code.replace("_", "-")


def upgrade() -> None:
    op.execute("""
        CREATE TABLE organization_backup_settings (
            tenant_id uuid PRIMARY KEY REFERENCES tenants(id) ON DELETE CASCADE,
            enabled boolean NOT NULL,
            cadence text NOT NULL CHECK (cadence IN ('daily', 'weekly')),
            local_time varchar(5) NOT NULL,
            weekday smallint NOT NULL CHECK (weekday BETWEEN 0 AND 6),
            destination jsonb NOT NULL,
            ftp_secret text,
            recovery_secret text,
            next_run_at timestamptz
        )
    """)
    op.execute("""
        CREATE TABLE organization_data_runs (
            id uuid PRIMARY KEY,
            tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            actor_id uuid,
            kind varchar(16) NOT NULL CHECK (kind IN ('manual','scheduled','import')),
            phase varchar(16) NOT NULL CHECK (phase IN ('export','preview','apply','transfer')),
            state varchar(16) NOT NULL CHECK (
                state IN ('uploading','queued','running','review','succeeded','failed','expired')
            ),
            transfer_state varchar(16),
            transfer_attempts smallint NOT NULL,
            options jsonb NOT NULL,
            secret text,
            summary jsonb NOT NULL,
            size_bytes bigint,
            checksum varchar(64),
            error_code text,
            due_at timestamptz NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            expires_at timestamptz NOT NULL,
            completed_at timestamptz
        )
    """)
    op.execute("""
        CREATE TABLE organization_import_receipts (
            run_id uuid PRIMARY KEY,
            tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            summary jsonb NOT NULL
        )
    """)
    op.execute("""
        CREATE INDEX idx_org_backup_schedule_due ON organization_backup_settings (next_run_at)
        WHERE enabled
    """)
    op.execute("""
        CREATE INDEX idx_org_data_run_history ON organization_data_runs (tenant_id, created_at DESC)
    """)
    op.execute("""
        CREATE INDEX idx_org_data_run_due ON organization_data_runs (due_at)
        WHERE state IN ('queued','running') OR transfer_state IN ('queued','running')
    """)
    op.execute("""
        CREATE INDEX idx_org_data_run_expiry ON organization_data_runs (expires_at)
        WHERE state <> 'expired'
    """)
    for table in (
        "organization_backup_settings",
        "organization_data_runs",
        "organization_import_receipts",
    ):
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO cbi_app")
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY tenant_isolation ON {table} USING (
                current_setting('app.staff', true) = 'on'
                OR tenant_id::text = current_setting('app.tenant_id', true)
            )
        """)
    bind = op.get_bind()
    articles = [("organization-data-backup", *GUIDE, "article")]
    articles.extend(
        (_error_slug(code), title, action, "error") for code, (title, action, _) in ERRORS.items()
    )
    for slug, title, body, kind in articles:
        bind.execute(
            sa.text("""
            INSERT INTO help_articles (slug, title, summary, body_html, body_plain,
                                       kind, status, published_at)
            VALUES (:slug, :title, :body, :html, :body, :kind, 'published', now())
        """),
            {
                "slug": slug,
                "title": title,
                "body": body,
                "html": f"<p>{escape(body)}</p>",
                "kind": kind,
            },
        )
    for code, (title, action, _) in ERRORS.items():
        bind.execute(
            sa.text("""
            INSERT INTO help_error_codes (code, article_id, severity, title, quick_action, source)
            SELECT :code, id, 'error', :title, :action, 'api'
            FROM help_articles WHERE slug = :slug
        """),
            {
                "code": code,
                "slug": _error_slug(code),
                "title": title,
                "action": action,
            },
        )


def downgrade() -> None:
    bind = op.get_bind()
    for code in ERRORS:
        bind.execute(sa.text("DELETE FROM help_error_codes WHERE code = :code"), {"code": code})
        bind.execute(
            sa.text("DELETE FROM help_articles WHERE slug = :slug"), {"slug": _error_slug(code)}
        )
    op.execute("DELETE FROM help_articles WHERE slug = 'organization-data-backup'")
    op.execute("DROP TABLE organization_import_receipts")
    op.execute("DROP TABLE organization_data_runs")
    op.execute("DROP TABLE organization_backup_settings")
