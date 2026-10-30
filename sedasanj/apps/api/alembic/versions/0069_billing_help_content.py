"""Seed the help-center articles and error-code pages for plans, billing and quotas."""

# ruff: noqa: E501 - the article text is long Persian prose that does not wrap usefully

import html

import sqlalchemy as sa

from alembic import op

revision = "0069_billing_help_content"
down_revision = "0068_notification_log"
branch_labels = None
depends_on = None

CATEGORY = ("plans-and-billing", "پلن‌ها و صورت‌حساب", "انتخاب پلن، پرداخت، تمدید و سهمیه")

# slug, title, summary, paragraphs / ordered steps (a list is rendered as a numbered list)
ARTICLES = [
    (
        "choose-and-change-plan",
        "انتخاب و تغییر پلن",
        "ارتقا همین حالا و به نسبت زمان باقی‌مانده پرداخت می‌شود؛ تنزل از پایان دوره اعمال می‌شود.",
        [
            "پرداخت اشتراک سالانه است. پلن فعلی شما در بخش «حساب» نمایش داده می‌شود.",
            [
                "از «حساب» روی «تغییر پلن» بزنید.",
                "پلن جدید و در صورت نیاز تعداد اپراتور اضافه را انتخاب کنید و ادامه دهید.",
                "برای ارتقا مبلغ تعدیل‌شده را از درگاه بپردازید؛ پلن بعد از پرداخت فعال می‌شود.",
                "برای تنزل چیزی پرداخت نمی‌شود و پلن جدید از پایان دوره فعلی شروع می‌شود.",
            ],
            "تا قبل از اعمال، تنزل برنامه‌ریزی‌شده را می‌توان از «حساب» لغو کرد.",
        ],
    ),
    (
        "cancel-and-renew-subscription",
        "لغو و تمدید اشتراک",
        "لغو یعنی عدم تمدید؛ اشتراک تا پایان دوره کار می‌کند و تا آن موقع قابل ازسرگیری است.",
        [
            "چند روز قبل از پایان دوره سفارش تمدید ساخته و برای مدیر سازمان ایمیل می‌شود.",
            [
                "از «حساب» سفارش تمدید را باز کنید و «پرداخت» را بزنید.",
                "اگر پرداخت نکنید، سرویس بعد از سررسید در مهلت تمدید کار می‌کند و سپس متوقف می‌شود.",
                "برای عدم تمدید، «لغو در پایان دوره» را بزنید؛ هر زمان تا سررسید می‌توانید «ازسرگیری» کنید.",
            ],
            "تمدید پیش از سررسید یک سال به انتهای دوره فعلی اضافه می‌کند و روز سررسید را جابه‌جا نمی‌کند.",
        ],
    ),
    (
        "minutes-and-assistant-quota",
        "سهمیه دقیقه و پیام دستیار",
        "دقیقه‌ها و پیام‌های هر ماه از سالگرد شروع اشتراک شما حساب می‌شوند.",
        [
            "دقیقه‌های رایگان پلن در شروع هر دوره ماهانه یک‌بار اضافه می‌شوند و در پایان همان دوره منقضی می‌شوند.",
            [
                "اول دقیقه‌های پلن مصرف می‌شود و بعد اعتبار پیش‌خریدی.",
                "پیام‌های دستیار هم از همان تاریخ سالگرد شمرده می‌شوند و فقط پیام‌های در حال انجام یا موفق مصرف حساب می‌شوند.",
                "با ارتقای پلن، دقیقه‌های اضافی ماه جاری به نسبت زمان باقی‌مانده اضافه می‌شود.",
            ],
            "اگر دقیقه‌ها تمام شد، از «حساب» اعتبار شارژ کنید یا پلن را ارتقا دهید.",
        ],
    ),
    (
        "failed-payment",
        "پرداخت ناموفق",
        "اگر پول کسر شد ولی سفارش پرداخت‌شده نشد، معمولاً تا چند دقیقه خودکار تأیید می‌شود.",
        [
            [
                "چند دقیقه صبر کنید و «سفارش‌ها» را در «حساب» تازه کنید.",
                "اگر سفارش هنوز «در انتظار پرداخت» است، با همان یا درگاه دیگری دوباره «پرداخت» را بزنید.",
                "اگر مبلغ از حساب شما کم شده و سفارش پرداخت نشد، شماره سفارش و کد پیگیری بانک را با پشتیبانی در میان بگذارید.",
            ],
            "مبلغ کسرشده در صورت عدم تأیید طبق قوانین بانک به حساب شما برمی‌گردد.",
        ],
    ),
    (
        "invoice-and-tax",
        "فاکتور و مالیات",
        "مالیات در صورت فعال‌بودن به‌صورت یک ردیف جدا در سفارش و فاکتور می‌آید.",
        [
            "فاکتور بعد از پرداخت صادر می‌شود و مبلغ بدون مالیات، مالیات و مبلغ نهایی را جدا نشان می‌دهد.",
            [
                "مبلغ پیش‌خرید اعتبار بدون مالیات به موجودی شما اضافه می‌شود.",
                "در بازپرداخت، مبلغ برگشتی از مبلغ نهایی سفارش بیشتر نخواهد بود.",
            ],
            "نرخ مالیات را مدیر سامانه تعیین می‌کند و در مرحله پرداخت دیده می‌شود.",
        ],
    ),
]

# code, article slug, title, severity, cause, steps, quick action
ERRORS = [
    (
        "subscription_exists",
        "اشتراک فعال دارید",
        "warning",
        "برای پلن دیگری سفارش خرید ساخته‌اید در حالی که اشتراک پولی در جریان است.",
        [
            "از «حساب» روی «تغییر پلن» بزنید.",
            "اگر می‌خواهید همان پلن را تمدید کنید، سفارش تمدید را پرداخت کنید.",
        ],
        "از «حساب» تغییر پلن را بزنید.",
    ),
    (
        "change_conflict",
        "تغییر پلن اکنون ممکن نیست",
        "warning",
        "دوره پولی تمام شده یا تغییر درخواستی با وضعیت فعلی اشتراک نمی‌خواند.",
        [
            "وضعیت اشتراک را در «حساب» ببینید.",
            "اگر دوره تمام شده است، اول اشتراک را تمدید کنید.",
            "تغییر برنامه‌ریزی‌شده قبلی را در صورت نیاز لغو کنید.",
        ],
        "اشتراک را در «حساب» بررسی کنید.",
    ),
    (
        "plan_not_sellable",
        "پلن قابل خرید نیست",
        "warning",
        "پلن انتخابی آزمایشی است، از فروش خارج شده یا فقط برای مشتریان فعلی است.",
        ["یکی از پلن‌های دیگر را انتخاب کنید.", "برای پلن اختصاصی با فروش تماس بگیرید."],
        "پلن دیگری انتخاب کنید.",
    ),
    (
        "plan_in_use",
        "پلن در حال استفاده است",
        "warning",
        "این تغییر پلنی را غیرفعال یا بازنشسته می‌کند که تنها نسخه قابل خرید یا دارای مشترک است.",
        [
            "اول نسخه جایگزین را منتشر کنید.",
            "اگر عمداً می‌خواهید پلن از فروش خارج شود، در تأیید دوم «ادامه» را بزنید.",
        ],
        "نسخه جایگزین را منتشر کنید.",
    ),
    (
        "plan_code_exists",
        "کد پلن تکراری است",
        "warning",
        "پلنی با همین کد قبلاً ساخته شده است.",
        ["کد دیگری انتخاب کنید یا پلن موجود را ویرایش کنید."],
        "کد دیگری انتخاب کنید.",
    ),
    (
        "order_amount_too_large",
        "مبلغ سفارش بیش از سقف مجاز است",
        "warning",
        "مبلغ سفارش از سقف تنظیم‌شده توسط مدیر سامانه بیشتر است.",
        ["تعداد دقیقه یا اپراتور را کمتر کنید.", "برای سفارش بزرگ‌تر با فروش تماس بگیرید."],
        "مقدار سفارش را کمتر کنید.",
    ),
    (
        "subscription_inactive",
        "اشتراک فعال نیست",
        "error",
        "اشتراک تمام شده و مهلت تمدید هم گذشته است، یا هنوز پرداخت نشده است.",
        [
            "از «حساب» سفارش تمدید را پرداخت کنید.",
            "اگر اعتبار پیش‌خریدی دارید، پردازش با همان انجام می‌شود.",
        ],
        "اشتراک را از «حساب» تمدید کنید.",
    ),
    (
        "insufficient_credit",
        "اعتبار کافی نیست",
        "error",
        "دقیقه‌های پلن و اعتبار پیش‌خریدی برای این پردازش کافی نیست.",
        ["از «حساب» اعتبار شارژ کنید.", "برای مصرف ماهانه بالا، پلن را ارتقا دهید."],
        "اعتبار را شارژ کنید.",
    ),
    (
        "quota_exceeded",
        "سقف مصرف پلن تمام شده است",
        "error",
        "سهمیه ماهانه پیام دستیار یا مصرف مجاز پلن تمام شده است.",
        [
            "تا شروع دوره بعد صبر کنید یا پلن را ارتقا دهید.",
            "تاریخ شروع دوره بعد در «حساب» دیده می‌شود.",
        ],
        "پلن را ارتقا دهید یا تا دوره بعد صبر کنید.",
    ),
]


def _slug(code: str) -> str:
    return "error-" + code.replace("_", "-")


def _body(blocks: list) -> tuple[str, str]:
    parts: list[str] = []
    plain: list[str] = []
    for block in blocks:
        if isinstance(block, list):
            items = "".join(f"<li>{html.escape(step)}</li>" for step in block)
            parts.append(f"<ol>{items}</ol>")
            plain.extend(block)
        else:
            parts.append(f"<p>{html.escape(block)}</p>")
            plain.append(block)
    return "".join(parts), " ".join(plain)


def error_blocks(cause: str, steps: list[str], code: str) -> list:
    return [
        "علائم: درخواست شما با خطا برگشت داده شد.",
        f"علت: {cause}",
        steps,
        "برای اطمینان، همان کار را دوباره انجام دهید؛ اگر باز هم خطا گرفتید با پشتیبانی تماس بگیرید و این کد را بگویید: "
        + code,
        "پیشگیری: وضعیت اشتراک و اعتبار را گاهی در «حساب» بررسی کنید.",
    ]


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "INSERT INTO help_categories (slug, title, description, position) "
            "VALUES (:slug, :title, :description, 50) ON CONFLICT (slug) DO NOTHING"
        ),
        {"slug": CATEGORY[0], "title": CATEGORY[1], "description": CATEGORY[2]},
    )
    category_id = bind.execute(
        sa.text("SELECT id FROM help_categories WHERE slug = :slug"), {"slug": CATEGORY[0]}
    ).scalar_one()
    insert_article = sa.text(
        "INSERT INTO help_articles (slug, category_id, title, summary, body_html, body_plain, "
        "kind, status, position, published_at) "
        "VALUES (:slug, :category, :title, :summary, :html, :plain, :kind, 'published', :position, now()) "
        "ON CONFLICT (slug) DO NOTHING"
    )
    for position, (slug, title, summary, blocks) in enumerate(ARTICLES):
        body_html, body_plain = _body(blocks)
        bind.execute(
            insert_article,
            {
                "slug": slug,
                "category": category_id,
                "title": title,
                "summary": summary,
                "html": body_html,
                "plain": body_plain,
                "kind": "article",
                "position": position,
            },
        )
    for position, (code, title, severity, cause, steps, quick) in enumerate(ERRORS):
        body_html, body_plain = _body(error_blocks(cause, steps, code))
        bind.execute(
            insert_article,
            {
                "slug": _slug(code),
                "category": category_id,
                "title": title,
                "summary": cause,
                "html": body_html,
                "plain": body_plain,
                "kind": "error",
                "position": 100 + position,
            },
        )
        bind.execute(
            sa.text(
                "INSERT INTO help_error_codes (code, article_id, source, severity, title, quick_action) "
                "SELECT :code, id, 'api', :severity, :title, :quick FROM help_articles WHERE slug = :slug "
                "ON CONFLICT (code) DO NOTHING"
            ),
            {
                "code": code,
                "severity": severity,
                "title": title,
                "quick": quick,
                "slug": _slug(code),
            },
        )


def downgrade() -> None:
    bind = op.get_bind()
    codes = [code for code, *_ in ERRORS]
    bind.execute(sa.text("DELETE FROM help_error_codes WHERE code = ANY(:codes)"), {"codes": codes})
    slugs = [slug for slug, *_ in ARTICLES] + [_slug(code) for code in codes]
    bind.execute(sa.text("DELETE FROM help_articles WHERE slug = ANY(:slugs)"), {"slugs": slugs})
    bind.execute(
        sa.text(
            "DELETE FROM help_categories WHERE slug = :slug AND NOT EXISTS "
            "(SELECT 1 FROM help_articles WHERE category_id = help_categories.id)"
        ),
        {"slug": CATEGORY[0]},
    )
