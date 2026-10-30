"""Per-gateway settings kept in the control database (`platform_settings`).

Credentials are Fernet-encrypted (`platform_secrets`).  `platform_settings` is control-only, so
payment flows running on a tenant session must load gateway state through `load_all()` (which
opens its own control session) instead of the tenant session.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import session_scope
from app.errors import ApiError
from app.models import PlatformSetting
from app.services.gateways.registry import GATEWAY_ORDER, GATEWAYS
from app.services.platform_secrets import decrypt_secret, encrypt_secret, secret_storage_error

PREFIX = "gateway."

# credential field -> Persian label (the admin form renders exactly these)
CREDENTIAL_FIELDS: dict[str, dict[str, str]] = {
    "zarinpal": {"merchant_id": "Merchant ID (۳۶ نویسه)"},
    "zibal": {"merchant_id": "Merchant ID"},
    "saman": {"terminal_id": "شماره ترمینال (TerminalId)"},
    "behpardakht": {
        "terminal_id": "شماره ترمینال (terminalId)",
        "username": "نام کاربری",
        "password": "رمز عبور",
    },
}
SANDBOX_GATEWAYS = {"zarinpal", "zibal"}
DESCRIPTIONS = {
    "zarinpal": "پرداخت با همه‌ی کارت‌های عضو شتاب از طریق زرین‌پال",
    "zibal": "پرداخت با همه‌ی کارت‌های عضو شتاب از طریق زیبال",
    "saman": "پرداخت مستقیم از درگاه بانک سامان (سپ)",
    "behpardakht": "پرداخت مستقیم از درگاه به‌پرداخت ملت",
}


@dataclass(frozen=True)
class GatewayState:
    code: str
    enabled: bool
    sandbox: bool
    credentials: dict[str, str] = field(default_factory=dict)

    @property
    def configured(self) -> bool:
        if self.sandbox and self.code == "zibal":
            return True
        return all(self.credentials.get(name) for name in CREDENTIAL_FIELDS[self.code])

    @property
    def usable(self) -> bool:
        return self.enabled and self.configured


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


async def _rows(session: AsyncSession) -> dict[str, str]:
    result = await session.execute(
        select(PlatformSetting).where(
            PlatformSetting.key.like(f"{PREFIX}%") | PlatformSetting.key.like("commerce.%")
        )
    )
    return {row.key: row.value for row in result.scalars()}


def _state(code: str, rows: dict[str, str]) -> GatewayState:
    prefix = f"{PREFIX}{code}."
    explicit = any(key.startswith(prefix) for key in rows)
    credentials: dict[str, str] = {}
    for name in CREDENTIAL_FIELDS[code]:
        raw = rows.get(prefix + name, "")
        credentials[name] = decrypt_secret(raw) if raw else ""
    if explicit or code != "zarinpal":
        return GatewayState(
            code,
            _truthy(rows.get(prefix + "enabled")),
            _truthy(rows.get(prefix + "sandbox")),
            credentials,
        )
    # Legacy ZarinPal configuration (`commerce.*` or environment) keeps working untouched.
    runtime = get_settings()
    merchant = rows.get("commerce.zarinpal_merchant_id") or runtime.zarinpal_merchant_id or ""
    enabled = (
        _truthy(rows["commerce.gateway_enabled"])
        if "commerce.gateway_enabled" in rows
        else bool(merchant)
    )
    sandbox = (
        _truthy(rows["commerce.zarinpal_sandbox"])
        if "commerce.zarinpal_sandbox" in rows
        else runtime.zarinpal_sandbox
    )
    return GatewayState("zarinpal", enabled, sandbox, {"merchant_id": merchant})


async def load_with(session: AsyncSession) -> dict[str, GatewayState]:
    rows = await _rows(session)
    return {code: _state(code, rows) for code in GATEWAY_ORDER}


async def load_all() -> dict[str, GatewayState]:
    """Gateway state from the control database, usable from any request or worker."""
    async with session_scope(staff=True) as control:
        return await load_with(control)


async def load_one(code: str) -> GatewayState:
    if code not in GATEWAYS:
        raise ApiError("not_found", "payment gateway not found")
    return (await load_all())[code]


async def save(
    session: AsyncSession,
    code: str,
    *,
    enabled: bool | None,
    sandbox: bool | None,
    credentials: dict[str, str],
) -> GatewayState:
    if code not in GATEWAYS:
        raise ApiError("not_found", "payment gateway not found")
    allowed = set(CREDENTIAL_FIELDS[code])
    unknown = set(credentials) - allowed
    if unknown:
        raise ApiError("invalid_request", "unknown credential field")
    if code == "zarinpal" and not any(
        key.startswith(f"{PREFIX}zarinpal.") for key in await _rows(session)
    ):
        # First explicit save: carry the legacy enabled/sandbox/merchant state over.
        legacy = (await load_with(session))["zarinpal"]
        for name, value in (
            ("enabled", "true" if legacy.enabled else "false"),
            ("sandbox", "true" if legacy.sandbox else "false"),
        ):
            session.add(PlatformSetting(key=f"{PREFIX}zarinpal.{name}", value=value))
        if legacy.credentials.get("merchant_id") and secret_storage_error() == "":
            session.add(
                PlatformSetting(
                    key=f"{PREFIX}zarinpal.merchant_id",
                    value=encrypt_secret(legacy.credentials["merchant_id"]),
                )
            )
        await session.flush()
    fresh = {k: v.strip() for k, v in credentials.items() if v and v.strip()}
    if fresh:
        problem = secret_storage_error()
        if problem:
            raise ApiError(
                "invalid_request",
                "PLATFORM_SECRETS_KEY is not configured; set it in deploy/.env first",
            )
    if "merchant_id" in fresh and code == "zarinpal" and len(fresh["merchant_id"]) != 36:
        raise ApiError("invalid_request", "ZarinPal merchant id must be 36 characters")

    async def put(name: str, value: str) -> None:
        key = f"{PREFIX}{code}.{name}"
        row = await session.get(PlatformSetting, key)
        if row is None:
            session.add(PlatformSetting(key=key, value=value))
        else:
            row.value = value

    for name, value in fresh.items():
        await put(name, encrypt_secret(value))
    if sandbox is not None:
        await put("sandbox", "true" if sandbox else "false")
    await session.flush()
    state = (await load_with(session))[code]
    if enabled is not None:
        if enabled and not state.configured:
            raise ApiError("invalid_request", "enter the gateway credentials before enabling it")
        await put("enabled", "true" if enabled else "false")
        await session.flush()
        state = (await load_with(session))[code]
    return state


def hint(value: str) -> str:
    return f"••••{value[-4:]}" if value else ""
