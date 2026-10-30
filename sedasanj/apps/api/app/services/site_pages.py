"""Editable public site pages (about, contact, legal): defaults, validation and storage keys.

Content is plain text only (no HTML) and stored as one JSON document per page in
``platform_settings``. A missing or unreadable document falls back to the built-in default, so a
public page never renders empty.
"""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

PageSlug = Literal["about", "contact", "terms", "privacy", "cancellation", "landing_video"]
PAGE_SLUGS: tuple[str, ...] = (
    "about",
    "contact",
    "terms",
    "privacy",
    "cancellation",
    "landing_video",
)
SETTING_KEY_PREFIX = "site_page_"

_LINK_RE = re.compile(r"^(/[^\s/][^\s]*|/|https://[^\s]+|tel:[+0-9]{5,20}|mailto:[^\s@]+@[^\s@]+)$")


def setting_key(slug: str) -> str:
    return f"{SETTING_KEY_PREFIX}{slug}"


def _text(max_length: int) -> Any:
    return Field(default="", max_length=max_length)


def _check_link(value: str) -> str:
    value = value.strip()
    if value and not _LINK_RE.match(value):
        raise ValueError("link must be an internal path, https://, tel: or mailto: address")
    return value


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


class TitledText(_Model):
    title: str = _text(120)
    text: str = _text(1200)


SiteIcon = Literal[
    "",
    "brain",
    "chart",
    "clock",
    "headset",
    "layers",
    "lock",
    "message",
    "phone",
    "pulse",
    "shield",
    "spark",
    "target",
    "tasks",
    "trend",
    "users",
]


class ValueItem(TitledText):
    icon: SiteIcon = ""


class AboutContent(_Model):
    hero_title: str = _text(200)
    hero_text: str = _text(1200)
    story_title: str = _text(200)
    story_paragraphs: list[str] = Field(default_factory=list, max_length=6)
    values_title: str = _text(200)
    values: list[ValueItem] = Field(default_factory=list, max_length=6)
    outcome_title: str = _text(200)
    outcome_text: str = _text(600)
    outcome_button: str = _text(80)
    outcome_link: str = _text(300)

    @field_validator("story_paragraphs")
    @classmethod
    def _paragraph_length(cls, value: list[str]) -> list[str]:
        if any(len(item) > 2000 for item in value):
            raise ValueError("a paragraph is longer than 2000 characters")
        return value

    @field_validator("outcome_link")
    @classmethod
    def _link(cls, value: str) -> str:
        return _check_link(value)


class ContactMethod(_Model):
    icon: Literal["sales", "mail", "clock", "phone", "location", "chat"] = "chat"
    label: str = _text(80)
    value: str = _text(200)
    href: str = _text(300)

    @field_validator("href")
    @classmethod
    def _link(cls, value: str) -> str:
        return _check_link(value)


class ContactContent(_Model):
    hero_title: str = _text(200)
    hero_text: str = _text(1200)
    aside_title: str = _text(120)
    methods: list[ContactMethod] = Field(default_factory=list, max_length=6)
    form_title: str = _text(160)
    form_message_placeholder: str = _text(300)
    form_submit: str = _text(60)
    form_success: str = _text(300)


class LegalSection(_Model):
    title: str = _text(160)
    body: str = _text(8000)


class LegalContent(_Model):
    title: str = _text(160)
    intro: str = _text(1200)
    updated_label: str = _text(80)
    sections: list[LegalSection] = Field(default_factory=list, max_length=40)


_MEDIA_ID_RE = re.compile(r"^$|^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


class LandingVideoContent(_Model):
    """The floating "why Sedasanj?" button on the landing page: label, GIF avatar, video."""

    title: str = _text(60)
    avatar_media_id: str = _text(36)
    video_media_id: str = _text(36)

    @field_validator("avatar_media_id", "video_media_id")
    @classmethod
    def _media_id(cls, value: str) -> str:
        value = value.strip().lower()
        if not _MEDIA_ID_RE.match(value):
            raise ValueError("must be the id of an uploaded media file or empty")
        return value


_MODELS: dict[str, type[BaseModel]] = {
    "about": AboutContent,
    "contact": ContactContent,
    "terms": LegalContent,
    "privacy": LegalContent,
    "cancellation": LegalContent,
    "landing_video": LandingVideoContent,
}

_ABOUT_DEFAULT: dict[str, Any] = {
    "hero_title": "برای شنیدن آنچه\n**میان هزاران تماس** پنهان می‌ماند.",
    "hero_text": (
        "صداسنج برای تبدیل مکالمات روزمره مرکز تماس به دانشی ساخته شده که مدیران بتوانند با آن "
        "کیفیت را بسنجند، مسئله‌ها را زودتر ببینند و تصمیم‌های دقیق‌تری بگیرند."
    ),
    "story_title": "فاصله میان شنیدن\nو واقعاً فهمیدن",
    "story_paragraphs": [
        (
            "در یک مرکز تماس، اطلاعات ارزشمند اغلب میان ساعت‌ها فایل صوتی گم می‌شوند. بررسی "
            "دستی تنها بخش کوچکی از تماس‌ها را پوشش می‌دهد و تصویر نهایی معمولاً دیر، ناقص و "
            "وابسته به برداشت فردی است."
        ),
        (
            "صداسنج این فاصله را با پردازش خودکار مکالمه فارسی، تحلیل محتوا و لحن، ارزیابی "
            "عملکرد، استخراج اقدام‌های بعدی و دستیار هوشمند سازمان کوتاه می‌کند."
        ),
    ],
    "values_title": "محصولی دقیق، انسانی و قابل اعتماد",
    "values": [
        {
            "icon": "target",
            "title": "فهم دقیق، نه حدس",
            "text": (
                "تصمیم خوب از داده‌ای شروع می‌شود که شفاف، قابل پیگیری و متصل به مکالمه واقعی باشد."
            ),
        },
        {
            "icon": "users",
            "title": "فناوری در خدمت انسان",
            "text": (
                "هوش مصنوعی باید زمان تیم را آزاد کند و در نهایت به تجربه بهتر مشتری و "
                "اپراتور برسد."
            ),
        },
        {
            "icon": "shield",
            "title": "اعتماد در تمام مسیر",
            "text": (
                "حریم داده، کنترل دسترسی و پاسخ‌گویی روشن، بخشی از محصول‌اند؛ نه گزینه‌ای برای بعد."
            ),
        },
    ],
    "outcome_title": "هر تماس باید به یک\nفرصت برای بهترشدن تبدیل شود.",
    "outcome_text": (
        "اگر می‌خواهید تصویر دقیق‌تری از صدای مشتریان و عملکرد تیم خود داشته باشید، با ما "
        "گفت‌وگو کنید."
    ),
    "outcome_button": "گفت‌وگو با تیم صداسنج",
    "outcome_link": "/contact",
}

_CONTACT_DEFAULT: dict[str, Any] = {
    "hero_title": "برای یک تصمیم دقیق‌تر،\n**گفت‌وگو را شروع کنیم.**",
    "hero_text": (
        "برای دریافت دمو، انتخاب پلن مناسب یا بررسی نحوه اتصال صداسنج به مرکز تماس شما، پیام "
        "بگذارید."
    ),
    "aside_title": "کنار شما هستیم.",
    "methods": [
        {
            "icon": "sales",
            "label": "فروش و درخواست دمو",
            "value": "فرم مشاوره همین صفحه",
            "href": "",
        },
        {
            "icon": "mail",
            "label": "پشتیبانی مشتریان",
            "value": "از داخل پنل سازمانی",
            "href": "/login",
        },
        {
            "icon": "clock",
            "label": "زمان پاسخ‌گویی",
            "value": "شنبه تا چهارشنبه، ۹ تا ۱۷",
            "href": "",
        },
    ],
    "form_title": "کمی از نیازتان برای ما بگویید.",
    "form_message_placeholder": (
        "درباره تعداد اپراتورها، حجم تماس یا نوع اتصال مورد نیاز بنویسید."
    ),
    "form_submit": "ثبت درخواست",
    "form_success": "درخواست شما ثبت شد؛ همکاران ما پیگیری می‌کنند.",
}

_LEGAL_INTRO = (
    "متن نهایی این سند پیش از فعال‌سازی پرداخت زنده توسط کسب‌وکار بازبینی و تأیید خواهد شد."
)


def _legal_default(title: str) -> dict[str, Any]:
    return {
        "title": title,
        "intro": _LEGAL_INTRO,
        "updated_label": "",
        "sections": [],
    }


DEFAULTS: dict[str, dict[str, Any]] = {
    "about": _ABOUT_DEFAULT,
    "contact": _CONTACT_DEFAULT,
    "terms": _legal_default("قوانین استفاده"),
    "privacy": _legal_default("حریم خصوصی"),
    "cancellation": _legal_default("سیاست لغو اشتراک"),
    "landing_video": {"title": "چرا صداسنج؟", "avatar_media_id": "", "video_media_id": ""},
}


def validate_content(slug: str, raw: Any) -> dict[str, Any]:
    """Canonical content for ``slug``; raises ``pydantic.ValidationError`` on bad input."""
    model = _MODELS[slug]
    return model.model_validate(raw).model_dump()


def default_content(slug: str) -> dict[str, Any]:
    return validate_content(slug, DEFAULTS[slug])


def load_content(slug: str, stored: str | None) -> tuple[dict[str, Any], bool]:
    """Stored JSON (or default) and whether the default was used."""
    if stored:
        try:
            return validate_content(slug, json.loads(stored)), False
        except ValueError:  # includes pydantic.ValidationError
            pass
    return default_content(slug), True


def dump_content(content: dict[str, Any]) -> str:
    return json.dumps(content, ensure_ascii=False, separators=(",", ":"))
