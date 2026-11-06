"""Admin-managed "meet SedaSanj" drawer content for the Jalase-Negar app.

Stored as one JSON document in ``platform_settings`` so no migration is needed.
"""

from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PlatformSetting

KEY = "jalase_negar_sedasanj_intro"
DEFAULT_BUTTON_URL = "https://sedasanj.ir"


def _https_url(value: str) -> str:
    if not value:
        return value
    if any(c.isspace() or ord(c) < 32 for c in value) or "\\" in value:
        raise ValueError("Use a valid HTTPS URL without spaces")
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Use a valid HTTPS URL")
    return value


class SedasanjIntro(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    enabled: bool = True
    # Days of use before the drawer first appears.
    delay_days: int = Field(default=3, ge=0, le=365)
    title: str = Field(default="با صداسنج آشنا شوید", min_length=1, max_length=120)
    body: str = Field(
        default=(
            "صداسنج مکالمات و جلسه‌های شما را ضبط، پیاده‌سازی و تحلیل می‌کند. "
            "با اتصال جلسه‌نگار به صداسنج، جلسه‌ها در حساب سازمان شما ذخیره می‌شوند، "
            "گفتار هر فرد جدا می‌شود و متن، خلاصه و وظایف جلسه از هر دستگاهی در دسترس است."
        ),
        max_length=2000,
    )
    # Empty means no video. Only https links are accepted; the app plays it in place.
    video_url: str = Field(default="", max_length=2048)
    button_label: str = Field(default="آشنایی با صداسنج", min_length=1, max_length=40)
    button_url: str = Field(default=DEFAULT_BUTTON_URL, min_length=1, max_length=2048)

    @field_validator("video_url", "button_url")
    @classmethod
    def https_only(cls, value: str) -> str:
        return _https_url(value)


async def load(session: AsyncSession) -> SedasanjIntro:
    row = await session.get(PlatformSetting, KEY)
    if row is None:
        return SedasanjIntro()
    try:
        return SedasanjIntro.model_validate_json(row.value)
    except ValueError:
        return SedasanjIntro()


async def save(session: AsyncSession, value: SedasanjIntro) -> None:
    from datetime import UTC, datetime

    row = await session.get(PlatformSetting, KEY)
    if row is None:
        session.add(PlatformSetting(key=KEY, value=value.model_dump_json()))
    else:
        row.value = value.model_dump_json()
        row.updated_at = datetime.now(UTC)
    await session.flush()
