"""Admin-managed Jalase-Negar output types (conversion categories) with versions and thumbnails."""

# ruff: noqa: E501 - Persian prompts are kept as complete sentences.

import json
from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

revision = "0147_jalase_output_types"
down_revision = "0146_jalase_signup_help"
branch_labels = None
depends_on = None

MINUTES_MAP = (
    "این بخشی از متن رونویسی‌شده‌ی یک جلسه است. موضوع‌های مطرح‌شده، تصمیم‌های صریح، اقدام‌ها "
    "(با مسئول و مهلت اگر در متن آمده)، نام‌ها، اعداد و تاریخ‌ها را فشرده و به ترتیب بنویس. "
    "چیزی را که در متن نیست اضافه نکن. فقط متن خلاصه را بنویس."
)
NO_INVENT = (
    " چیزی را که در متن نیست اضافه نکن؛ نام، عدد، آیه، روایت و تاریخ را فقط اگر در متن آمده بنویس."
)

# (code, title, description, menu_label, mode, map_instruction, system_prompt)
DRAFTS = (
    (
        "counseling",
        "بازنویسی جلسهٔ مشاوره",
        "گزارش ساختاریافتهٔ جلسهٔ مشاوره برای مشاور: موضوع‌ها، احساس‌ها و تکلیف‌های بین جلسه.",
        "جلسات مشاوره",
        "summarize",
        "این بخشی از متن رونویسی‌شدهٔ یک جلسهٔ مشاوره است. موضوع‌های مطرح‌شده، احساس‌ها و نگرانی‌های مراجع، "
        "پیشنهادها و تکلیف‌های مشاور را فشرده و به ترتیب بنویس." + NO_INVENT,
        "تو دستیار یک مشاور هستی و از متن جلسه یک گزارش مشاوره می‌نویسی. بخش‌ها: «موضوع‌های اصلی»، "
        "«احساس‌ها و نگرانی‌های مراجع»، «پیشنهادها و مداخله‌های مشاور»، «تکلیف‌های بین جلسه» و «نکته‌های جلسهٔ بعد». "
        "لحن محترمانه و بی‌قضاوت باشد و برچسب تشخیصی نزن." + NO_INVENT,
    ),
    (
        "hawza_lecture",
        "تقریر درس حوزوی",
        "تقریر منظم درس: طرح مسئله، ادله، اقوال، نقد و نتیجه.",
        "تقریر درس",
        "summarize",
        "این بخشی از متن رونویسی‌شدهٔ یک درس حوزوی است. مسئلهٔ مطرح‌شده، اقوال، ادله، اشکال‌ها و پاسخ‌ها و نتیجه را "
        "فشرده و به ترتیب بنویس." + NO_INVENT,
        "تو دستیار یک طلبه هستی و از متن درس یک تقریر منظم می‌نویسی. بخش‌ها: «موضوع و طرح مسئله»، «اقوال»، «ادله»، "
        "«اشکال‌ها و پاسخ‌ها»، «نتیجه». آیات، روایات و اصطلاحات را فقط به همان شکلی که در متن آمده بنویس."
        + NO_INVENT,
    ),
    (
        "university_notes",
        "جزوهٔ کلاس دانشگاهی",
        "جزوهٔ مرتب با سرفصل، تعریف‌ها، مثال‌ها و نکته‌های امتحانی.",
        "جزوه‌ها",
        "summarize",
        "این بخشی از متن رونویسی‌شدهٔ یک کلاس دانشگاهی است. سرفصل‌ها، تعریف‌ها، قضیه‌ها یا قاعده‌ها، مثال‌ها و "
        "تأکیدهای استاد را فشرده و به ترتیب بنویس." + NO_INVENT,
        "تو دستیار یک دانشجو هستی و از متن کلاس یک جزوهٔ مرتب می‌نویسی. بخش‌ها به‌ترتیب سرفصل‌های کلاس، و در هر بخش "
        "تعریف‌ها، مثال‌ها و «نکته‌های امتحانی» (فقط جاهایی که استاد تأکید یا اعلام کرده)."
        + NO_INVENT,
    ),
    (
        "clean_text",
        "متن تمیزشده",
        "فقط ویرایش و نگارش درست متن گفتار، بدون خلاصه‌کردن.",
        "متن‌های تمیزشده",
        "transform",
        "",
        "متن رونویسی‌شدهٔ گفتار را به فارسی روان و درست بازنویسی کن: غلط‌های نگارشی و تکرارهای بی‌معنی و «ام»ها را حذف کن، "
        "جمله‌ها را کامل کن و پاراگراف‌بندی کن. هیچ بخشی را خلاصه یا حذف نکن و معنی را عوض نکن. فقط متن بازنویسی‌شده را بنویس.",
    ),
    (
        "action_list",
        "فهرست کارها",
        "اقدام‌ها با مسئول و مهلت، بدون شرح اضافه.",
        "فهرست کارها",
        "summarize",
        "این بخشی از متن رونویسی‌شدهٔ یک گفتگو است. فقط کارهایی را که کسی پذیرفته یا قرار شده انجام شود، با مسئول و مهلت "
        "اگر آمده، فشرده بنویس." + NO_INVENT,
        "از متن، فهرست کارها را بساز. هر کار یک آیتم است و در خود متن آن مسئول و مهلت (اگر در متن آمده) نوشته شود. "
        "بخش‌ها: «کارهای قطعی» و «کارهای احتمالی یا نیازمند تأیید»." + NO_INVENT,
    ),
    (
        "interview",
        "پیاده‌سازی مصاحبه",
        "پیاده‌سازی پرسش و پاسخ با نام گوینده‌ها، برای پژوهش یا خبر.",
        "مصاحبه‌ها",
        "transform",
        "",
        "متن رونویسی‌شدهٔ یک مصاحبه را به فارسی روان و به‌صورت پرسش و پاسخ بازنویسی کن. نام گوینده‌ها را همان‌طور که در متن آمده "
        "حفظ کن، غلط‌های نگارشی و تکرارهای بی‌معنی را اصلاح کن و هیچ پاسخی را خلاصه نکن. فقط متن مصاحبه را بنویس.",
    ),
    (
        "talk_summary",
        "خلاصهٔ سخنرانی، وبینار یا منبر",
        "خلاصهٔ محورها، نکته‌های کلیدی و جمع‌بندی سخنرانی.",
        "سخنرانی‌ها",
        "summarize",
        "این بخشی از متن رونویسی‌شدهٔ یک سخنرانی است. محورهای اصلی، مثال‌ها و نکته‌های کلیدی را فشرده و به ترتیب بنویس."
        + NO_INVENT,
        "از متن سخنرانی یک خلاصه بنویس. بخش‌ها: «محورهای اصلی»، «نکته‌های کلیدی»، «نقل‌قول‌های مهم» (فقط عبارت‌های عیناً موجود در متن) "
        "و «جمع‌بندی»." + NO_INVENT,
    ),
    (
        "flashcards",
        "فلش‌کارت و پرسش مرور",
        "پرسش و پاسخ‌های کوتاه برای مرور مطلب.",
        "فلش‌کارت‌ها",
        "summarize",
        "این بخشی از متن رونویسی‌شدهٔ یک آموزش است. مفهوم‌ها، تعریف‌ها و واقعیت‌های قابل مرور را فشرده بنویس."
        + NO_INVENT,
        "از متن، فلش‌کارت‌های مرور بساز. در هر بخش، هر نکته به‌صورت «پرسش: … — پاسخ: …» نوشته شود. پرسش‌ها کوتاه و پاسخ‌ها دقیق و "
        "فقط بر پایهٔ متن باشند." + NO_INVENT,
    ),
)


def upgrade() -> None:
    op.execute("""CREATE TABLE jalase_output_types (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    code VARCHAR(40) NOT NULL,
    title_fa VARCHAR(120) NOT NULL,
    description_fa VARCHAR(500) NOT NULL DEFAULT '',
    menu_label_fa VARCHAR(60) NOT NULL,
    thumbnail_media_id UUID,
    sort_order INTEGER NOT NULL DEFAULT 100,
    status VARCHAR(16) NOT NULL DEFAULT 'draft',
    builtin BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT jalase_output_types_code_key UNIQUE (code),
    CONSTRAINT jalase_output_types_code_check CHECK (code ~ '^[a-z][a-z0-9_]{1,39}$'),
    CONSTRAINT jalase_output_types_status_check CHECK (status IN ('draft','published','archived')),
    FOREIGN KEY(thumbnail_media_id) REFERENCES help_media (id) ON DELETE SET NULL
)""")
    op.execute("""CREATE TABLE jalase_output_type_versions (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    output_type_id UUID NOT NULL,
    version INTEGER NOT NULL,
    state VARCHAR(16) NOT NULL DEFAULT 'draft',
    mode VARCHAR(16) NOT NULL DEFAULT 'summarize',
    map_instruction TEXT NOT NULL DEFAULT '',
    system_prompt TEXT NOT NULL DEFAULT '',
    input_fields JSONB NOT NULL DEFAULT '[]'::jsonb,
    llm_provider VARCHAR(40),
    llm_model VARCHAR(120),
    created_by UUID,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    published_at TIMESTAMP WITH TIME ZONE,
    PRIMARY KEY (id),
    CONSTRAINT jalase_output_type_versions_unique UNIQUE (output_type_id, version),
    CONSTRAINT jalase_output_type_versions_state_check CHECK (state IN ('draft','published','superseded')),
    CONSTRAINT jalase_output_type_versions_mode_check CHECK (mode IN ('summarize','transform')),
    CONSTRAINT jalase_output_type_versions_number_check CHECK (version >= 1),
    FOREIGN KEY(output_type_id) REFERENCES jalase_output_types (id) ON DELETE CASCADE,
    FOREIGN KEY(created_by) REFERENCES staff_users (id) ON DELETE SET NULL
)""")
    op.execute(
        "CREATE INDEX idx_jalase_output_types_listing ON jalase_output_types (status, sort_order)"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_jalase_output_type_one_published ON jalase_output_type_versions "
        "(output_type_id) WHERE state = 'published'"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON jalase_output_types TO cbi_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON jalase_output_type_versions TO cbi_app")

    bind = op.get_bind()
    insert_type = sa.text(
        "INSERT INTO jalase_output_types (code,title_fa,description_fa,menu_label_fa,sort_order,"
        "status,builtin) VALUES (:code,:title,:description,:menu,:sort,:status,:builtin) RETURNING id"
    )
    insert_version = sa.text(
        "INSERT INTO jalase_output_type_versions (output_type_id,version,state,mode,map_instruction,"
        "system_prompt,input_fields,published_at) VALUES (:tid,1,:state,:mode,:map,:prompt,"
        "CAST(:fields AS jsonb),:published)"
    )
    minutes_id = bind.execute(
        insert_type,
        {
            "code": "minutes",
            "title": "صورت‌جلسه",
            "description": "صورت‌جلسهٔ رسمی با خلاصه، تصمیم‌ها و اقدام‌ها.",
            "menu": "صورت‌جلسات",
            "sort": 10,
            "status": "published",
            "builtin": True,
        },
    ).scalar_one()
    # The built-in type runs the existing minutes engine: its prompt is the platform's meeting prompt.
    bind.execute(
        insert_version,
        {
            "tid": minutes_id,
            "state": "published",
            "mode": "summarize",
            "map": MINUTES_MAP,
            "prompt": "",
            "fields": "[]",
            "published": datetime.now(UTC),
        },
    )
    for order, (code, title, description, menu, mode, map_instruction, prompt) in enumerate(
        DRAFTS, start=1
    ):
        type_id = bind.execute(
            insert_type,
            {
                "code": code,
                "title": title,
                "description": description,
                "menu": menu,
                "sort": 10 + order * 10,
                "status": "draft",
                "builtin": False,
            },
        ).scalar_one()
        bind.execute(
            insert_version,
            {
                "tid": type_id,
                "state": "draft",
                "mode": mode,
                "map": map_instruction,
                "prompt": prompt,
                "fields": json.dumps([]),
                "published": None,
            },
        )


def downgrade() -> None:
    op.drop_table("jalase_output_type_versions")
    op.drop_table("jalase_output_types")
