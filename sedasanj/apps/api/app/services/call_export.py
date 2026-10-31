"""Column catalogue and rendering for the calls export (CSV and XLSX)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from zoneinfo import ZoneInfo

from app.errors import ApiError
from app.schemas import CallSummary
from app.services import assistant_export_renderers

TEHRAN = ZoneInfo("Asia/Tehran")
FORMATS = ("xlsx", "csv")
MEDIA_TYPES = {fmt: assistant_export_renderers.MEDIA_TYPES[fmt] for fmt in FORMATS}
MAX_ROWS = 20000

DIRECTION_LABELS = {"inbound": "ورودی", "outbound": "خروجی", "internal": "داخلی"}
CALL_TYPE_LABELS = {
    "answered": "پاسخ‌داده‌شده",
    "missed": "بی‌پاسخ",
    "busy": "مشغول",
    "congestion": "اختلال / اشغال مسیر",
    "failed": "ناموفق",
    "canceled": "لغوشده",
    "voicemail": "پیام‌گیر صوتی",
}
INTENT_LABELS = {
    "technical_support": "پشتیبانی فنی",
    "sales_inquiry": "استعلام فروش",
    "complaint": "شکایت",
    "consultation": "مشاوره",
    "billing": "امور مالی",
    "other": "سایر",
}
SENTIMENT_LABELS = {
    "angry": "عصبانی",
    "sad": "ناراحت",
    "neutral": "خنثی",
    "satisfied": "راضی",
    "happy": "خوشحال",
}
TRAJECTORY_LABELS = {"improved": "بهبود", "worsened": "افت", "stable": "ثابت"}


def to_jalali(moment: datetime) -> str:
    """`YYYY/MM/DD HH:MM:SS` in the Jalali calendar and Tehran time (Latin digits)."""
    local = moment.astimezone(TEHRAN)
    gy, gm, gd = local.year, local.month, local.day
    cumulative = (0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334)
    gy2 = gy + 1 if gm > 2 else gy
    days = (
        355666
        + 365 * gy
        + (gy2 + 3) // 4
        - (gy2 + 99) // 100
        + (gy2 + 399) // 400
        + gd
        + cumulative[gm - 1]
    )
    jy = -1595 + 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm, jd = 1 + days // 31, 1 + days % 31
    else:
        jm, jd = 7 + (days - 186) // 30, 1 + (days - 186) % 30
    return f"{jy:04d}/{jm:02d}/{jd:02d} {local:%H:%M:%S}"


def _duration(call: CallSummary) -> str:
    total = max(0, round(call.duration_ms / 1000))
    return f"{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}"


# key -> (Persian label, value getter, operator-visible)
COLUMNS: dict[str, tuple[str, Callable[[CallSummary], object], bool]] = {
    "started_at": ("زمان شروع", lambda c: to_jalali(c.started_at), True),
    "ended_at": ("زمان پایان", lambda c: to_jalali(c.ended_at), True),
    "caller_number": ("شمارهٔ تماس‌گیرنده", lambda c: c.caller_number or "", True),
    "caller_name": ("نام تماس‌گیرنده", lambda c: c.caller_name or "", True),
    "dialed_number": ("شمارهٔ مقصد", lambda c: c.dialed_number or "", True),
    "dialed_name": ("نام مقصد", lambda c: c.dialed_name or "", True),
    "direction": ("جهت تماس", lambda c: DIRECTION_LABELS.get(c.direction or "", ""), True),
    "agent_extension": ("داخلی", lambda c: c.agent_extension or "", True),
    "duration": ("مدت (ساعت:دقیقه:ثانیه)", _duration, True),
    "billed_seconds": ("ثانیهٔ محاسبه‌شده", lambda c: c.billed_seconds, False),
    "call_type": ("نوع تماس", lambda c: CALL_TYPE_LABELS.get(c.call_type, c.call_type), True),
    "intent": ("قصد", lambda c: INTENT_LABELS.get(c.intent or "", c.intent or ""), True),
    "sentiment": (
        "احساس",
        lambda c: SENTIMENT_LABELS.get(c.sentiment or "", c.sentiment or ""),
        True,
    ),
    "sentiment_trajectory": (
        "روند احساس",
        lambda c: TRAJECTORY_LABELS.get(c.sentiment_trajectory or "", ""),
        True,
    ),
    "summary": ("خلاصه", lambda c: c.summary or "", True),
}


def parse_columns(raw: str, *, include_billing: bool) -> list[str]:
    """Validate the comma separated column keys; the catalogue order wins over the request order."""
    requested = {key.strip() for key in raw.split(",") if key.strip()}
    allowed = {key for key, (_, _, public) in COLUMNS.items() if public or include_billing}
    if not requested:
        raise ApiError("invalid_request", "حداقل یک ستون را برای خروجی انتخاب کنید")
    if requested - allowed:
        raise ApiError(
            "invalid_request", "ستون انتخاب‌شده معتبر نیست؛ فهرست ستون‌ها را دوباره باز کنید"
        )
    return [key for key in COLUMNS if key in requested]


def render(fmt: str, keys: Sequence[str], calls: Sequence[CallSummary]) -> bytes:
    labels = {key: COLUMNS[key][0] for key in keys}
    rows = [{key: COLUMNS[key][1](call) for key in keys} for call in calls]
    return assistant_export_renderers.render(fmt, labels, rows, sheet_title="تماس‌ها")
