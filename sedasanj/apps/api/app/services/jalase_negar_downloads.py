"""Public download options for Jalase-Negar: store links and Windows/macOS installers.

Store links are one JSON document in ``platform_settings``; installers are rows in
``jalase_negar_desktop_builds`` with the file in object storage.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiError
from app.models import JalaseNegarDesktopBuild, PlatformSetting
from app.services.jalase_sedasanj_intro import _https_url

KEY = "jalase_negar_store_links"
KEY_PREFIX = "jalase-negar-desktop/"
Platform = Literal["windows", "macos"]
ALLOWED_EXTENSIONS: dict[str, tuple[str, ...]] = {
    "windows": (".exe", ".msi", ".zip"),
    "macos": (".dmg", ".pkg", ".zip"),
}
_VERSION_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z.+_-]{0,31}$")
_NAME_RE = re.compile(r"[^0-9A-Za-z._-]+")


class StoreLinks(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    bazaar: str = Field(default="", max_length=2048)
    myket: str = Field(default="", max_length=2048)
    google_play: str = Field(default="", max_length=2048)
    app_store: str = Field(default="", max_length=2048)
    anardoni: str = Field(default="", max_length=2048)
    sibapp: str = Field(default="", max_length=2048)

    @field_validator("*")
    @classmethod
    def https_only(cls, value: str) -> str:
        return _https_url(value)


async def load_links(session: AsyncSession) -> StoreLinks:
    row = await session.get(PlatformSetting, KEY)
    if row is None:
        return StoreLinks()
    try:
        return StoreLinks.model_validate_json(row.value)
    except ValueError:
        return StoreLinks()


async def save_links(session: AsyncSession, value: StoreLinks) -> None:
    row = await session.get(PlatformSetting, KEY)
    if row is None:
        session.add(PlatformSetting(key=KEY, value=value.model_dump_json()))
    else:
        row.value = value.model_dump_json()
        row.updated_at = datetime.now(UTC)
    await session.flush()


def validate_upload(platform: str, version: str, filename: str) -> tuple[str, str]:
    """Return a safe (version, file_name); raise ``invalid_request`` with the next step."""
    version = version.strip()
    if platform not in ALLOWED_EXTENSIONS:
        raise ApiError("invalid_request", "platform must be windows or macos")
    if not _VERSION_RE.match(version):
        raise ApiError(
            "invalid_request", "the version may use letters, digits and . + _ - (for example 1.2.0)"
        )
    lowered = filename.lower()
    extension = next((e for e in ALLOWED_EXTENSIONS[platform] if lowered.endswith(e)), None)
    if extension is None:
        allowed = ", ".join(ALLOWED_EXTENSIONS[platform])
        raise ApiError("invalid_request", f"the {platform} installer must be one of: {allowed}")
    return version, f"jalase-negar-{platform}-{version}{extension}"


def artifact_key(build_id: UUID, file_name: str) -> str:
    return f"{KEY_PREFIX}{_NAME_RE.sub('_', build_id.hex)}/{file_name}"


def latest_per_platform(
    builds: list[JalaseNegarDesktopBuild],
) -> dict[str, JalaseNegarDesktopBuild]:
    result: dict[str, JalaseNegarDesktopBuild] = {}
    for build in sorted(builds, key=lambda b: b.created_at):
        result[build.platform] = build
    return result
