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
    installation_initial_toman: int
    installation_reinstall_toman: int
    installation_dedicated_toman: int
    renewal_lead_days: int
    terms_version: str
    terms_url: str
    tax_percent: int
    automatic_discounts_enabled: bool
    grace_days: int
    payment_window_days: int
    order_ttl_days: int
    renewal_price_policy: str
    max_order_toman: int
    credit_min_minutes: int
    credit_max_minutes: int
    credit_presets: str
    featured_plan_code: str
    default_price_per_minute_toman: int


def _bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


async def get_commerce_settings(session: AsyncSession) -> CommerceSettings:
    base = get_settings()
    defaults = {
        "gateway_enabled": bool(base.zarinpal_merchant_id),
        "zarinpal_merchant_id": base.zarinpal_merchant_id or "",
        "zarinpal_sandbox": base.zarinpal_sandbox,
        "installation_initial_toman": 0,
        "installation_reinstall_toman": 3_000_000,
        "installation_dedicated_toman": 20_000_000,
        "renewal_lead_days": 7,
        "terms_version": "1",
        "terms_url": "",
        "tax_percent": 0,
        "automatic_discounts_enabled": False,
        "grace_days": 3,
        "payment_window_days": 7,
        "order_ttl_days": 14,
        "renewal_price_policy": "keep",
        "max_order_toman": 5_000_000_000,
        "credit_min_minutes": 10,
        "credit_max_minutes": 1_000_000,
        "credit_presets": "60,300,1000,3000",
        "featured_plan_code": "silver",
        "default_price_per_minute_toman": 7_000,
    }
    rows = (
        (
            await session.execute(
                select(PlatformSetting).where(PlatformSetting.key.like(f"{PREFIX}%"))
            )
        )
        .scalars()
        .all()
    )
    values = {row.key.removeprefix(PREFIX): row.value for row in rows}
    bool_keys = {"gateway_enabled", "zarinpal_sandbox", "automatic_discounts_enabled"}
    int_keys = {
        "installation_initial_toman",
        "installation_reinstall_toman",
        "installation_dedicated_toman",
        "renewal_lead_days",
        "tax_percent",
        "grace_days",
        "payment_window_days",
        "order_ttl_days",
        "max_order_toman",
        "credit_min_minutes",
        "credit_max_minutes",
        "default_price_per_minute_toman",
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


def credit_preset_minutes(value: CommerceSettings) -> list[int]:
    """Parse the comma separated preset list, keeping only values inside the allowed range."""
    presets: list[int] = []
    for part in value.credit_presets.split(","):
        part = part.strip()
        if part.isdigit() and value.credit_min_minutes <= int(part) <= value.credit_max_minutes:
            presets.append(int(part))
    return presets
