from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import PlatformSetting

PREFIX = "commerce."


@dataclass(frozen=True)
class CommerceSettings:
    gateway_enabled: bool
    zarinpal_merchant_id: str
    zarinpal_sandbox: bool
    custom_credit_price_per_minute_toman: int
    installation_initial_toman: int
    installation_reinstall_toman: int
    installation_dedicated_toman: int
    renewal_lead_days: int
    terms_version: str
    terms_url: str
    tax_percent: int
    automatic_discounts_enabled: bool


def _bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


async def get_commerce_settings(session: AsyncSession) -> CommerceSettings:
    base = get_settings()
    defaults = {
        "gateway_enabled": bool(base.zarinpal_merchant_id),
        "zarinpal_merchant_id": base.zarinpal_merchant_id or "",
        "zarinpal_sandbox": base.zarinpal_sandbox,
        "custom_credit_price_per_minute_toman": 2_000,
        "installation_initial_toman": 0,
        "installation_reinstall_toman": 3_000_000,
        "installation_dedicated_toman": 20_000_000,
        "renewal_lead_days": 7,
        "terms_version": "1",
        "terms_url": "",
        "tax_percent": 0,
        "automatic_discounts_enabled": False,
    }
    rows = (
        await session.execute(
            select(PlatformSetting).where(PlatformSetting.key.like(f"{PREFIX}%"))
        )
    ).scalars().all()
    values = {row.key.removeprefix(PREFIX): row.value for row in rows}
    bool_keys = {"gateway_enabled", "zarinpal_sandbox", "automatic_discounts_enabled"}
    int_keys = {
        "custom_credit_price_per_minute_toman",
        "installation_initial_toman",
        "installation_reinstall_toman",
        "installation_dedicated_toman",
        "renewal_lead_days",
        "tax_percent",
    }
    for key, raw in values.items():
        if key in bool_keys:
            defaults[key] = _bool(raw)
        elif key in int_keys:
            defaults[key] = int(raw)
        elif key in defaults:
            defaults[key] = raw
    return CommerceSettings(**cast(Any, defaults))


async def update_commerce_settings(
    session: AsyncSession, changes: dict[str, object]
) -> CommerceSettings:
    allowed = set(asdict(await get_commerce_settings(session)))
    for key, value in changes.items():
        if key not in allowed or value is None:
            continue
        row = await session.get(PlatformSetting, f"{PREFIX}{key}")
        serialized = str(value).lower() if isinstance(value, bool) else str(value).strip()
        if row is None:
            session.add(PlatformSetting(key=f"{PREFIX}{key}", value=serialized))
        else:
            row.value = serialized
    await session.flush()
    return await get_commerce_settings(session)


def public_view(value: CommerceSettings) -> dict[str, object]:
    data = asdict(value)
    secret = str(data.pop("zarinpal_merchant_id"))
    data["merchant_id_configured"] = bool(secret)
    data["merchant_id_hint"] = f"••••{secret[-4:]}" if secret else ""
    return data
