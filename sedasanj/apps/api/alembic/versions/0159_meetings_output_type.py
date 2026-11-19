"""Meetings carry the output type chosen before recording; the builtin one is renamed."""

import sqlalchemy as sa

from alembic import op

revision = "0159_meetings_output_type"
down_revision = "0158_jalase_store_billing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE meetings ADD COLUMN output_type_code text")
    op.execute(
        "ALTER TABLE meetings ADD COLUMN output_type_input_values jsonb "
        "NOT NULL DEFAULT '{}'::jsonb"
    )
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE jalase_output_types SET title_fa = :title, menu_label_fa = :menu "
            "WHERE code = 'minutes' AND builtin"
        ),
        {"title": "صورت جلسه عمومی", "menu": "صورت‌جلسات عمومی"},
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE jalase_output_types SET title_fa = :title, menu_label_fa = :menu "
            "WHERE code = 'minutes' AND builtin"
        ),
        {"title": "صورت‌جلسه", "menu": "صورت‌جلسات"},
    )
    op.execute("ALTER TABLE meetings DROP COLUMN output_type_input_values")
    op.execute("ALTER TABLE meetings DROP COLUMN output_type_code")
