"""Add Jalase-Negar Android releases that the app offers as in-app update suggestions."""

from alembic import op

revision = "0097_jalase_negar_releases"
down_revision = "0096_meeting_text_help_content"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE TABLE jalase_negar_releases (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    package_name VARCHAR(128) NOT NULL,
    version_name VARCHAR(32) NOT NULL,
    version_code BIGINT NOT NULL,
    min_sdk INTEGER NOT NULL,
    abis VARCHAR(32)[] DEFAULT '{}'::varchar[] NOT NULL,
    title VARCHAR(200) NOT NULL,
    changelog_html TEXT DEFAULT '' NOT NULL,
    changelog_plain TEXT DEFAULT '' NOT NULL,
    artifact_key TEXT NOT NULL,
    artifact_sha256 CHAR(64) NOT NULL,
    artifact_size BIGINT NOT NULL,
    signing_cert_sha256 CHAR(64) NOT NULL,
    status VARCHAR(16) NOT NULL,
    published_at TIMESTAMP WITH TIME ZONE,
    revoked_at TIMESTAMP WITH TIME ZONE,
    created_by UUID,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT jalase_negar_releases_version_code_key UNIQUE (version_code),
    CONSTRAINT jalase_negar_releases_version_name_key UNIQUE (version_name),
    CONSTRAINT jalase_negar_releases_status_check
        CHECK (status IN ('draft','published','revoked')),
    CONSTRAINT jalase_negar_releases_version_code_check CHECK (version_code > 0),
    FOREIGN KEY(created_by) REFERENCES staff_users (id) ON DELETE SET NULL
)""")
    op.execute(
        "CREATE INDEX idx_jalase_negar_releases_status "
        "ON jalase_negar_releases (status, version_code DESC)"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON jalase_negar_releases TO cbi_app")


def downgrade() -> None:
    op.drop_table("jalase_negar_releases")
