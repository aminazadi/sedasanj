"""Validated public footer content stored in platform settings."""

from typing import Annotated, Literal, get_args
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

DEFAULT_COPYRIGHT = "© ۱۴۰۵ صداسنج. تمامی حقوق این وب‌سایت برای صداسنج محفوظ است."
SocialNetwork = Literal["eitaa", "bale", "telegram", "instagram", "aparat", "youtube"]


class FooterLink(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    label: str = Field(min_length=1, max_length=120)
    url: str = Field(min_length=1, max_length=2048)

    @field_validator("url")
    @classmethod
    def safe_url(cls, value: str) -> str:
        if any(character.isspace() or ord(character) < 32 for character in value) or "\\" in value:
            raise ValueError("Use a site path or a valid HTTPS/HTTP URL without spaces")
        if value.startswith("/") and not value.startswith("//"):
            return value
        parsed = urlsplit(value)
        if (
            parsed.scheme in {"https", "http"}
            and parsed.hostname
            and not parsed.username
            and not parsed.password
        ):
            return value
        raise ValueError("Use a site path beginning with / or a valid HTTPS/HTTP URL")


class FooterSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    contact_title: str = Field(default="با ما تماس بگیرید", max_length=200)
    contact_description: str = Field(default="پذیرای صدای گرم شما خواهیم بود", max_length=2000)
    about_title: str = Field(default="درباره صداسنج", max_length=200)
    description: str = Field(default="سامانه هوشمند تحلیل مکالمات فارسی", max_length=4000)
    links_title: str = Field(default="لینک‌های پرکاربرد", max_length=200)
    trust_title: str = Field(default="نمادهای اعتماد", max_length=200)
    copyright: str = Field(default=DEFAULT_COPYRIGHT, max_length=500)
    address: str = Field(default="", max_length=500)
    social_links: dict[SocialNetwork, Annotated[str, Field(max_length=2048)]] = Field(
        default_factory=dict
    )
    links: list[FooterLink] = Field(
        default_factory=lambda: [
            FooterLink(label="امکانات", url="/#features"),
            FooterLink(label="پلن‌ها", url="/#pricing"),
            FooterLink(label="درباره ما", url="/about"),
            FooterLink(label="تماس با ما", url="/contact"),
            FooterLink(label="ورود به پنل", url="/login"),
        ],
        max_length=30,
    )
    legal_links: list[FooterLink] = Field(
        default_factory=lambda: [
            FooterLink(label="قوانین استفاده", url="/terms"),
            FooterLink(label="حریم خصوصی", url="/privacy"),
            FooterLink(label="لغو اشتراک", url="/cancellation"),
        ],
        max_length=30,
    )

    @field_validator("social_links", mode="before")
    @classmethod
    def validate_social_networks(cls, links: object) -> object:
        if isinstance(links, dict) and set(links).difference(get_args(SocialNetwork)):
            raise ValueError("Use one of the supported social networks")
        return links

    @field_validator("social_links")
    @classmethod
    def validate_social_links(cls, links: dict[SocialNetwork, str]) -> dict[SocialNetwork, str]:
        configured = {}
        for network, value in links.items():
            if not value:
                continue
            try:
                FooterLink.safe_url(value)
                parsed = urlsplit(value)
                valid = (
                    value.startswith("https://")
                    and parsed.username is None
                    and parsed.password is None
                    and parsed.port != 0
                )
            except ValueError:
                valid = False
            if not valid:
                raise ValueError("Enter a complete HTTPS URL for each configured social network")
            configured[network] = value
        return configured

    @field_validator("copyright")
    @classmethod
    def refresh_legacy_copyright(cls, value: str) -> str:
        if value == "© ۱۴۰۵ صداسنج":
            return DEFAULT_COPYRIGHT
        return value
