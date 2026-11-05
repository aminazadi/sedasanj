"""Persist and protect the original organization administrator."""

# ruff: noqa: E501 - Persian help prose is kept in complete paragraphs.

import sqlalchemy as sa

from alembic import op

revision = "0114_primary_organization_admin"
down_revision = "0113_user_panel_access_help"
branch_labels = None
depends_on = None

PRIMARY_HTML = '<h2 data-primary-admin="true">مدیر اصلی سازمان</h2><p data-primary-admin="true">حساب سازندهٔ سازمان، مدیر اصلی است. هیچ کاربری نمی\u200cتواند این حساب را حذف کند یا نقش و دسترسی آن را تغییر دهد. در سازمان\u200cهای قدیمی، قدیمی\u200cترین حساب مدیر به\u200cعنوان مدیر اصلی ثبت می\u200cشود. برای مدیریت اعضا، حساب دیگری را انتخاب کنید.</p>'
PRIMARY_PLAIN = " مدیر اصلی سازمان قابل حذف یا تغییر نقش و دسترسی نیست. primary_admin_protected"


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_primary_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.execute("""UPDATE users SET is_primary_admin = true, panel_permissions = NULL
        WHERE id IN (SELECT DISTINCT ON (tenant_id) id FROM users
                     WHERE role = 'org_admin' ORDER BY tenant_id, created_at, id)""")
    op.create_check_constraint(
        "users_primary_admin_access",
        "users",
        "NOT is_primary_admin OR (role = 'org_admin' AND panel_permissions IS NULL)",
    )
    op.create_index(
        "users_primary_admin_key",
        "users",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("is_primary_admin"),
    )
    op.execute("""CREATE FUNCTION protect_primary_organization_admin() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.is_primary_admin THEN
                IF TG_OP = 'DELETE' THEN
                    RAISE EXCEPTION 'primary_admin_protected' USING ERRCODE = '23514';
                END IF;
                IF NEW.id IS DISTINCT FROM OLD.id OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
                   OR NEW.is_primary_admin IS DISTINCT FROM OLD.is_primary_admin
                   OR NEW.role IS DISTINCT FROM OLD.role
                   OR NEW.panel_permissions IS DISTINCT FROM OLD.panel_permissions THEN
                    RAISE EXCEPTION 'primary_admin_protected' USING ERRCODE = '23514';
                END IF;
            END IF;
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END;
        $$""")
    op.execute("""CREATE TRIGGER users_protect_primary_admin BEFORE UPDATE OR DELETE ON users
                  FOR EACH ROW EXECUTE FUNCTION protect_primary_organization_admin()""")
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "INSERT INTO help_error_codes (code, article_id, source, severity, title, quick_action) "
            "SELECT 'primary_admin_protected', id, 'api', 'warning', :title, :action "
            "FROM help_articles WHERE slug = 'user-panel-access' ON CONFLICT (code) DO NOTHING"
        ),
        {
            "title": "مدیر اصلی سازمان محافظت شده است",
            "action": "مدیر اصلی قابل حذف یا تغییر دسترسی نیست؛ کاربر دیگری را انتخاب کنید.",
        },
    )
    bind.execute(
        sa.text(
            "UPDATE help_articles SET body_html = body_html || :body, body_plain = body_plain || :plain WHERE slug = 'user-panel-access'"
        ),
        {"body": PRIMARY_HTML, "plain": PRIMARY_PLAIN},
    )


def downgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "UPDATE help_articles SET body_html = replace(body_html, :body, ''), body_plain = replace(body_plain, :plain, '') WHERE slug = 'user-panel-access'"
        ),
        {"body": PRIMARY_HTML, "plain": PRIMARY_PLAIN},
    )
    op.execute("DELETE FROM help_error_codes WHERE code = 'primary_admin_protected'")
    op.execute("DROP TRIGGER users_protect_primary_admin ON users")
    op.execute("DROP FUNCTION protect_primary_organization_admin()")
    op.drop_index("users_primary_admin_key", table_name="users")
    op.drop_constraint("users_primary_admin_access", "users", type_="check")
    op.drop_column("users", "is_primary_admin")
