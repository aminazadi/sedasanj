"""ML model registry: published model artifacts stored under `ml-models/` in the main bucket.

Follows the integrated speaker profile and Android rollout migrations.
"""

from alembic import op

revision = "0110_ml_model_releases"
down_revision = "0109_jalase_negar_update_install_help"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE TABLE ml_model_releases (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    kind VARCHAR(64) NOT NULL,
    version VARCHAR(64) NOT NULL,
    channel VARCHAR(16) NOT NULL,
    status VARCHAR(16) NOT NULL,
    artifact_key TEXT NOT NULL,
    sha256 CHAR(64) NOT NULL,
    size_bytes BIGINT NOT NULL,
    dim INTEGER,
    sample_rate INTEGER,
    metrics JSONB DEFAULT '{}'::jsonb NOT NULL,
    dataset_manifest_hash VARCHAR(128),
    training_run_id VARCHAR(128),
    signature TEXT,
    rollout_percent INTEGER DEFAULT 0 NOT NULL,
    pinned BOOLEAN DEFAULT false NOT NULL,
    published_by_key UUID,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    ready_at TIMESTAMP WITH TIME ZONE,
    promoted_at TIMESTAMP WITH TIME ZONE,
    superseded_at TIMESTAMP WITH TIME ZONE,
    revoked_at TIMESTAMP WITH TIME ZONE,
    deleted_at TIMESTAMP WITH TIME ZONE,
    PRIMARY KEY (id),
    CONSTRAINT ml_model_releases_kind_version_key UNIQUE (kind, version),
    CONSTRAINT ml_model_releases_channel_check CHECK (channel IN ('latest','champion')),
    CONSTRAINT ml_model_releases_status_check
        CHECK (status IN ('uploading','ready','revoked','deleted')),
    CONSTRAINT ml_model_releases_rollout_check CHECK (rollout_percent BETWEEN 0 AND 100)
)""")
    op.execute(
        "CREATE INDEX idx_ml_model_releases_kind ON ml_model_releases "
        "(kind, channel, status, created_at DESC)"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ml_model_releases TO cbi_app")


def downgrade() -> None:
    op.drop_table("ml_model_releases")
