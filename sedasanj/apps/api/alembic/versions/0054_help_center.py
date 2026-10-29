"""Add the help center: categories, articles, error-code mapping and media."""

from alembic import op

revision = "0054_help_center"
down_revision = "0053_module_releases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE TABLE help_categories (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    slug VARCHAR(80) NOT NULL,
    title VARCHAR(200) NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    position INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT help_categories_slug_key UNIQUE (slug),
    CONSTRAINT help_categories_slug_check CHECK (slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$')
)""")
    op.execute("""CREATE TABLE help_articles (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    slug VARCHAR(120) NOT NULL,
    category_id UUID,
    title VARCHAR(250) NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    body_html TEXT NOT NULL DEFAULT '',
    body_plain TEXT NOT NULL DEFAULT '',
    kind VARCHAR(16) NOT NULL DEFAULT 'article',
    status VARCHAR(16) NOT NULL DEFAULT 'draft',
    position INTEGER NOT NULL DEFAULT 0,
    published_at TIMESTAMP WITH TIME ZONE,
    created_by UUID,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    search_tsv tsvector GENERATED ALWAYS AS (
        to_tsvector('simple', coalesce(title, '') || ' ' || coalesce(summary, '') || ' '
                    || coalesce(body_plain, ''))
    ) STORED,
    PRIMARY KEY (id),
    CONSTRAINT help_articles_slug_key UNIQUE (slug),
    CONSTRAINT help_articles_slug_check CHECK (slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
    CONSTRAINT help_articles_kind_check CHECK (kind IN ('article','error','faq')),
    CONSTRAINT help_articles_status_check CHECK (status IN ('draft','published')),
    FOREIGN KEY(category_id) REFERENCES help_categories (id) ON DELETE SET NULL,
    FOREIGN KEY(created_by) REFERENCES staff_users (id) ON DELETE SET NULL
)""")
    op.execute("CREATE INDEX idx_help_articles_search ON help_articles USING gin (search_tsv)")
    op.execute(
        "CREATE INDEX idx_help_articles_listing ON help_articles (status, category_id, position)"
    )
    op.execute("""CREATE TABLE help_error_codes (
    code VARCHAR(40) NOT NULL,
    article_id UUID,
    source VARCHAR(16) NOT NULL DEFAULT 'module',
    severity VARCHAR(16) NOT NULL DEFAULT 'error',
    title VARCHAR(250) NOT NULL DEFAULT '',
    quick_action TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (code),
    CONSTRAINT help_error_codes_code_check CHECK (code ~ '^[A-Za-z0-9_.-]{2,40}$'),
    CONSTRAINT help_error_codes_source_check CHECK (source IN ('module','api','worker')),
    CONSTRAINT help_error_codes_severity_check
        CHECK (severity IN ('info','warning','error','critical')),
    FOREIGN KEY(article_id) REFERENCES help_articles (id) ON DELETE SET NULL
)""")
    op.execute("CREATE INDEX idx_help_error_codes_article ON help_error_codes (article_id)")
    op.execute("""CREATE TABLE help_media (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    kind VARCHAR(16) NOT NULL,
    object_key TEXT NOT NULL,
    filename VARCHAR(255) NOT NULL,
    content_type VARCHAR(100) NOT NULL,
    size_bytes BIGINT NOT NULL,
    alt VARCHAR(300) NOT NULL DEFAULT '',
    created_by UUID,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT help_media_key_key UNIQUE (object_key),
    CONSTRAINT help_media_kind_check CHECK (kind IN ('image','video')),
    FOREIGN KEY(created_by) REFERENCES staff_users (id) ON DELETE SET NULL
)""")
    for table in ("help_categories", "help_articles", "help_error_codes", "help_media"):
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO cbi_app")


def downgrade() -> None:
    op.drop_table("help_media")
    op.drop_table("help_error_codes")
    op.drop_table("help_articles")
    op.drop_table("help_categories")
