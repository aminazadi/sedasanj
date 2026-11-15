"""Cafe Bazaar / Myket purchases for Jalase-Negar: SKU map, used-token ledger and help."""

# ruff: noqa: E501 - Persian help prose is kept in complete paragraphs.

import sqlalchemy as sa

from alembic import op

revision = "0158_jalase_store_billing"
down_revision = "0157_jalase_delete_help"
branch_labels = None
depends_on = None

SLUG = "jalase-negar-store-purchase"
TITLE = "خرید پلن از کافه‌بازار و مایکت"
SUMMARY = "خرید یک ماه پلن یا بستهٔ توکن از مارکت، تأیید سمت سرور و رفع خطاهای رایج."
BODY = (
    "<h2>چطور کار می‌کند</h2><p>در نسخه‌های کافه‌بازار و مایکت، خرید با پرداخت خود مارکت انجام می‌شود. اپ توکن خرید را به سرور می‌فرستد، سرور آن را با رابط رسمی همان مارکت بررسی می‌کند و فقط پس از تأیید، پلن یا بستهٔ توکن را فعال می‌کند. هر خرید فقط یک بار قابل استفاده است. پلن‌ها در مارکت «محصول یک‌بار مصرف» با مدت یک ماه‌اند؛ مایکت اشتراک تمدیدشونده ندارد، پس برای ماه بعد باید دوباره خرید کنید.</p>"
    '<h2>خطاها</h2><ul><li><code dir="ltr">store_purchase_invalid</code>: مارکت این خرید را تأیید نکرد یا محصول در فهرست فروش نیست.</li>'
    '<li><code dir="ltr">store_purchase_already_used</code>: این خرید قبلاً برای حساب دیگری فعال شده است.</li>'
    '<li><code dir="ltr">store_verify_unavailable</code>: ارتباط سرور با مارکت برقرار نشد یا اتصال سرور به مارکت هنوز تنظیم نشده است.</li>'
    '<li><code dir="ltr">plan_not_found</code>: پلن انتخاب‌شده وجود ندارد؛ فهرست پلن‌ها را تازه کنید.</li></ul>'
    "<h2>رفع مشکل</h2><ol><li>اگر پول از حساب شما کم شده ولی پلن فعال نشده، دوباره صفحهٔ پلن‌ها را باز کنید؛ اپ خرید ثبت‌شده را دوباره به سرور می‌فرستد.</li>"
    "<li>اگر همچنان فعال نشد، شمارهٔ پیگیری مارکت را برای پشتیبانی بفرستید.</li></ol>"
    '<h2>برای مدیر</h2><p>در تنظیمات سرور مقدارهای اتصال به بازار (<code dir="ltr">BAZAAR_CLIENT_ID</code>، <code dir="ltr">BAZAAR_CLIENT_SECRET</code>، <code dir="ltr">BAZAAR_REFRESH_TOKEN</code>) و مایکت (<code dir="ltr">MYKET_ACCESS_TOKEN</code>) و نام بستهٔ اپ (<code dir="ltr">JALASE_ANDROID_PACKAGE</code>) لازم است و محصول‌های مارکت باید در جدول محصولات فروش ثبت شوند.</p>'
)
CODES = {
    "store_purchase_invalid": (
        "مارکت این خرید را تأیید نکرد.",
        "پرداخت را از مارکت بررسی و دوباره تلاش کنید.",
    ),
    "store_purchase_already_used": (
        "این خرید قبلاً استفاده شده است.",
        "با همان حسابی که خرید کردید وارد شوید.",
    ),
    "store_verify_unavailable": (
        "تأیید خرید از مارکت اکنون ممکن نیست.",
        "چند دقیقه بعد دوباره تلاش کنید.",
    ),
    "plan_not_found": ("پلن پیدا نشد.", "فهرست پلن‌ها را تازه کنید."),
}


def upgrade() -> None:
    op.execute("""CREATE TABLE store_skus (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        store varchar(12) NOT NULL CHECK (store IN ('bazaar','myket')),
        sku varchar(64) NOT NULL,
        kind varchar(8) NOT NULL CHECK (kind IN ('plan','pack')),
        plan_code varchar(32),
        package_id uuid REFERENCES token_packages(id),
        active boolean NOT NULL DEFAULT true,
        CHECK ((kind = 'plan' AND plan_code IS NOT NULL) OR (kind = 'pack' AND package_id IS NOT NULL)),
        UNIQUE (store, sku))""")
    op.execute("""CREATE TABLE store_purchases (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        store varchar(12) NOT NULL CHECK (store IN ('bazaar','myket')),
        token_hash varchar(64) NOT NULL,
        sku varchar(64) NOT NULL,
        tenant_id uuid NOT NULL REFERENCES tenants(id),
        order_id uuid,
        state varchar(12) NOT NULL DEFAULT 'pending' CHECK (state IN ('pending','granted')),
        created_at timestamptz NOT NULL DEFAULT now(),
        UNIQUE (store, token_hash))""")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON store_skus TO cbi_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON store_purchases TO cbi_app")
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "INSERT INTO help_articles (slug,title,summary,body_html,body_plain,kind,status,"
            "position,published_at) "
            "VALUES (:slug,:title,:summary,:body,:summary,'article','published',158,now()) "
            "ON CONFLICT (slug) DO NOTHING"
        ),
        {"slug": SLUG, "title": TITLE, "summary": SUMMARY, "body": BODY},
    )
    for code, (title, action) in CODES.items():
        bind.execute(
            sa.text(
                "INSERT INTO help_error_codes (code,source,severity,article_id,title,quick_action) "
                "SELECT :code,'api','error',id,:title,:action "
                "FROM help_articles WHERE slug=:slug ON CONFLICT (code) DO NOTHING"
            ),
            {"slug": SLUG, "code": code, "title": title, "action": action},
        )


def downgrade() -> None:
    bind = op.get_bind()
    for code in CODES:
        bind.execute(sa.text("DELETE FROM help_error_codes WHERE code=:code"), {"code": code})
    bind.execute(sa.text("DELETE FROM help_articles WHERE slug=:slug"), {"slug": SLUG})
    op.execute("DROP TABLE IF EXISTS store_purchases")
    op.execute("DROP TABLE IF EXISTS store_skus")
