"""Create draft help articles for the most common module errors (idempotent; never overwrites).

    DATABASE_URL=... uv run python scripts/seed_help_articles.py

Articles are created as drafts and linked to their error codes. Review them in the admin panel
(مرکز راهنما), add screenshots or videos, then publish.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from sqlalchemy import select  # noqa: E402

from app.db import session_scope  # noqa: E402
from app.models import HelpArticle, HelpErrorCode  # noqa: E402
from app.services import help_content  # noqa: E402


def body(symptom: str, cause: str, steps: list[str], verify: str, prevent: str = "") -> str:
    items = "".join(f"<li>{s}</li>" for s in steps)
    html = (
        f"<h2>علائم</h2><p>{symptom}</p><h2>علت</h2><p>{cause}</p>"
        f"<h2>راه‌حل</h2><ol>{items}</ol><h2>چطور مطمئن شوم درست شد؟</h2><p>{verify}</p>"
    )
    return html + (f"<h2>پیشگیری</h2><p>{prevent}</p>" if prevent else "")


ARTICLES = [
    (
        "ss-upl-0401",
        "کلید API رد شد (HTTP 401)",
        ["SS-UPL-0401", "unauthorized"],
        body(
            "در صفحهٔ ماژول «Paused: key or account» می‌بینید و ضبط‌ها آپلود نمی‌شوند.",
            "سرور کلید API را نپذیرفت: کلید اشتباه، باطل‌شده یا مربوط به سازمان دیگری است.",
            [
                "در پنل صداسنج کلید جدید بسازید.",
                "فایل پیکربندی را دانلود و در ماژول «Import Configuration» اعمال کنید.",
                "نیازی به آپلود دوباره نیست؛ ضبط‌های صف‌شده خودکار ادامه می‌یابند.",
            ],
            "شمارندهٔ «Paused» صفر می‌شود و لاگ پیام Uploaded دارد.",
            "کلید را قبل از باطل‌کردن در همهٔ سرورها جایگزین کنید.",
        ),
    ),
    (
        "ss-upl-0402",
        "اعتبار تمام شده است (HTTP 402)",
        ["SS-UPL-0402", "insufficient_credit"],
        body(
            "آپلودها با وضعیت «Blocked by credit» می‌مانند.",
            "موجودی دقیقه یا اشتراک پایان یافته است.",
            [
                "از پنل، اعتبار یا اشتراک را تمدید کنید.",
                "منتظر بمانید؛ صف هر ساعت دوباره تلاش می‌کند.",
            ],
            "پس از شارژ، شمارندهٔ Blocked by credit کم می‌شود.",
        ),
    ),
    (
        "ss-upl-0403",
        "دسترسی ممنوع یا حساب معلق (HTTP 403)",
        ["SS-UPL-0403", "forbidden", "tenant_suspended"],
        body(
            "آپلود با خطای 403 متوقف می‌شود.",
            "حساب سازمان معلق شده یا کلید اجازهٔ لازم را ندارد.",
            ["وضعیت اشتراک را در پنل بررسی کنید.", "اگر مشکل مالی نیست با پشتیبانی تماس بگیرید."],
            "پس از رفع تعلیق، صف خودکار ادامه می‌دهد.",
        ),
    ),
    (
        "ss-upl-0404",
        "مسیر endpoint اشتباه است (HTTP 404)",
        ["SS-UPL-0404", "SS-CFG-1004"],
        body(
            "آپلود با 404 متوقف می‌شود یا ماژول از endpoint شکایت می‌کند.",
            "نشانی باید با /v1/ingest/calls تمام شود و https باشد.",
            [
                "در تب Upload Endpoint نشانی را اصلاح کنید: https://…/v1/ingest/calls.",
                "ذخیره کنید و سرویس را ری‌استارت بگذارید.",
            ],
            "دستور doctor.php وضعیت API health را OK نشان می‌دهد.",
        ),
    ),
    (
        "ss-upl-0413",
        "فایل برای سرور بزرگ است (HTTP 413)",
        ["SS-UPL-0413", "archive_too_large"],
        body(
            "فقط تماس‌های طولانی رد می‌شوند.",
            "حجم فایل از سقف سرور یا reverse proxy بیشتر است.",
            [
                "اگر پراکسی دارید client_max_body_size را بالا ببرید.",
                "ضبط‌های بسیار طولانی را کوتاه کنید.",
            ],
            "تماس طولانی بعدی آپلود می‌شود.",
        ),
    ),
    (
        "ss-upl-0415",
        "فرمت آپلود با کلید همخوان نیست (HTTP 415)",
        ["SS-UPL-0415", "unsupported_archive", "unsupported_audio"],
        body(
            "همهٔ آپلودها 415 می‌گیرند.",
            "کلید برای gzip یا zip ساخته شده ولی ماژول فرمت دیگری می‌فرستد.",
            [
                "در پنل فرمت کلید را ببینید.",
                "همان را در تب Upload Endpoint (Upload Format) انتخاب کنید.",
            ],
            "آپلود بعدی موفق است.",
        ),
    ),
    (
        "ss-upl-2005",
        "مشکل TLS یا ساعت سرور",
        ["SS-UPL-2005"],
        body(
            "خطای certificate یا SSL در لاگ.",
            "ساعت PBX غلط است یا ca-certificates قدیمی است.",
            [
                "ساعت را با NTP درست کنید.",
                "ca-certificates را به‌روز کنید.",
                "verify_tls را در محیط واقعی خاموش نکنید.",
            ],
            "دستور curl -v به endpoint بدون خطای certificate پاسخ می‌دهد.",
        ),
    ),
    (
        "ss-upl-2002",
        "DNS یا شبکه کار نمی‌کند",
        ["SS-UPL-2001", "SS-UPL-2002", "SS-UPL-2003", "SS-UPL-2004"],
        body(
            "آپلودها با خطای شبکه یا timeout شکست می‌خورند و دوباره تلاش می‌شوند.",
            "PBX به endpoint دسترسی ندارد یا لینک کند است.",
            [
                "از PBX دستور curl -v روی endpoint را اجرا کنید.",
                "DNS و فایروال خروجی را بررسی کنید.",
                "برای ضبط‌های طولانی timeout را بالا ببرید.",
            ],
            "doctor.php در بخش DNS و API health وضعیت OK دارد.",
        ),
    ),
    (
        "ss-hook-1005",
        "تغییر callrecording توسط FreePBX و توقف هوک",
        ["SS-HOOK-1005"],
        body(
            "ضبط‌های جدید دیگر به صداسنج نمی‌رسند و در صفحهٔ سلامت patch «missing» است.",
            "ماژول callrecording به‌روز شده و patch ما پاک شده است.",
            ["دستور activate.sh را دوباره به‌عنوان root اجرا کنید."],
            "در تب Health & Dependencies همه‌چیز سبز است.",
            "پس از هر به‌روزرسانی FreePBX این دستور را اجرا کنید.",
        ),
    ),
    (
        "ss-sys-1004",
        "فعال‌سازی root لازم است",
        ["SS-SYS-1004"],
        body(
            "بنر «Activation required» بالای صفحهٔ ماژول.",
            "Module Admin بدون root نصب می‌کند و سرویس را نمی‌سازد.",
            ["دستور نمایش‌داده‌شده را با sudo روی PBX اجرا کنید.", "صفحه را دوباره باز کنید."],
            "بنر ناپدید و سرویس running است.",
        ),
    ),
    (
        "ss-hook-1003",
        "ادغام استریو شکست خورد",
        ["SS-HOOK-1003"],
        body(
            "در لاگ SS-HOOK-1003 هست و تماس تک‌کاناله آپلود شده.",
            "یکی از دو فایل کانال خراب یا فرمت ضبط wav نیست.",
            ["فرمت ضبط FreePBX را WAV کنید.", "فضای دیسک را بررسی کنید."],
            "تماس بعدی استریو آپلود می‌شود.",
        ),
    ),
]


async def main() -> None:
    created = 0
    async with session_scope(None, staff=True) as session:
        for slug, title, codes, html in ARTICLES:
            if (
                await session.execute(select(HelpArticle.id).where(HelpArticle.slug == slug))
            ).first():
                continue
            safe, plain = help_content.sanitize_help_html(html)
            article = HelpArticle(
                slug=slug,
                title=title,
                summary=title,
                body_html=safe,
                body_plain=plain,
                kind="error",
                status="draft",
            )
            session.add(article)
            await session.flush()
            for code in codes:
                existing = await session.get(HelpErrorCode, code)
                if existing is None:
                    session.add(HelpErrorCode(code=code, article_id=article.id, title=title))
                elif existing.article_id is None:
                    existing.article_id = article.id
            created += 1
    print(f"created {created} draft article(s)")


asyncio.run(main())
