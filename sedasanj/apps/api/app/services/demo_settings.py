from __future__ import annotations

from dataclasses import asdict, dataclass
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.errors import ApiError
from app.models import PlatformSetting
from app.services.platform_secrets import decrypt_secret, encrypt_secret

PREFIX = "quick_demo."


@dataclass
class DemoSettings:
    enabled: bool = True
    smsir_api_key: str = ""
    smsir_base_url: str = "https://api.sms.ir/v1"
    smsir_template_id: int = 0
    smsir_code_parameter: str = "CODE"
    otp_ttl_seconds: int = 120
    otp_resend_seconds: int = 60
    otp_max_attempts: int = 5
    session_ttl_minutes: int = 15
    max_duration_seconds: int = 120
    max_calls_per_mobile: int = 0
    max_total_minutes: int = 0
    prompt_object_key: str = ""


async def load(session: AsyncSession) -> DemoSettings:
    base = get_settings()
    value = DemoSettings(
        smsir_api_key=base.smsir_api_key or "",
        smsir_base_url=base.smsir_base_url,
        smsir_template_id=base.smsir_verify_template_id or 0,
    )
    rows = (
        (
            await session.execute(
                select(PlatformSetting).where(PlatformSetting.key.like(f"{PREFIX}%"))
            )
        )
        .scalars()
        .all()
    )
    for row in rows:
        key = row.key.removeprefix(PREFIX)
        if key == "smsir_api_key":
            value.smsir_api_key = decrypt_secret(row.value)
        elif key == "enabled":
            value.enabled = row.value == "true"
        elif key in asdict(value):
            setattr(
                value, key, int(row.value) if isinstance(getattr(value, key), int) else row.value
            )
    return value


async def save(session: AsyncSession, changes: dict[str, object]) -> DemoSettings:
    if "smsir_base_url" in changes:
        url = urlsplit(str(changes["smsir_base_url"]))
        if (
            url.scheme != "https"
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            raise ApiError("invalid_request", "آدرس SMS.ir باید یک نشانی HTTPS معتبر باشد.")
        changes["smsir_base_url"] = str(changes["smsir_base_url"]).rstrip("/")
    for key, raw in changes.items():
        if key not in DemoSettings.__dataclass_fields__:
            continue
        if key == "smsir_api_key":
            if not str(raw).strip():
                continue
            try:
                serialized = encrypt_secret(str(raw))
            except RuntimeError as exc:
                raise ApiError("invalid_request", str(exc)) from exc
        else:
            serialized = str(raw).lower() if isinstance(raw, bool) else str(raw).strip()
        row = await session.get(PlatformSetting, f"{PREFIX}{key}")
        if row is None:
            session.add(PlatformSetting(key=f"{PREFIX}{key}", value=serialized))
        else:
            row.value = serialized
    await session.flush()
    return await load(session)


def public_view(value: DemoSettings) -> dict[str, object]:
    data = asdict(value)
    secret = str(data.pop("smsir_api_key"))
    data.pop("prompt_object_key")
    data["smsir_api_key_configured"] = bool(secret)
    data["smsir_api_key_hint"] = f"••••{secret[-4:]}" if secret else ""
    data["prompt_configured"] = bool(value.prompt_object_key)
    data["prompt_url"] = "/v1/quick-demo/prompt" if value.prompt_object_key else None
    return data
