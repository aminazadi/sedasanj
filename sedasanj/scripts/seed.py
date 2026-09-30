"""Seed a staff account, a demo tenant with credit, and display packages.

Manual:
  uv run python scripts/seed.py --tenant "شرکت نمونه" --minutes 600

Deploy (idempotent; creates only what is missing):
  python /srv/app/scripts/seed.py --from-env
"""

from __future__ import annotations

import argparse
import asyncio
import os
import secrets
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from sqlalchemy import select  # noqa: E402

from app.db import dispose_engine, session_scope  # noqa: E402
from app.models import ApiKey, Package, StaffUser, Tenant, TenantBalanceCache, User  # noqa: E402
from app.security import generate_api_key, hash_password, materialize_api_key  # noqa: E402
from app.services import billing  # noqa: E402

DEFAULT_PACKAGES = [
    ("پایه — ۵۰۰ دقیقه", 500, 5_000_000),
    ("حرفه‌ای — ۲۰۰۰ دقیقه", 2000, 18_000_000),
    ("سازمانی — ۱۰۰۰۰ دقیقه", 10000, 80_000_000),
]


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return value.strip()


async def seed(
    tenant_name: str,
    admin_email: str,
    staff_email: str,
    minutes: int,
    price_per_minute: int,
    *,
    admin_password: str | None = None,
    staff_password: str | None = None,
    reset_passwords: bool = False,
    tenant_id: UUID | None = None,
    api_key: str | None = None,
    require_passwords_on_create: bool = False,
) -> None:
    resolved_admin_password = admin_password or secrets.token_urlsafe(12)
    resolved_staff_password = staff_password or secrets.token_urlsafe(12)

    async with session_scope(None, staff=True) as session:
        staff = (
            await session.execute(select(StaffUser).where(StaffUser.email == staff_email))
        ).scalar_one_or_none()
        if staff is None:
            if require_passwords_on_create and not staff_password:
                raise SystemExit("SEED_STAFF_PASSWORD is required to create the staff user")
            staff = StaffUser(
                email=staff_email,
                password_hash=hash_password(resolved_staff_password),
                role="super_admin",
            )
            session.add(staff)
            staff_password_out = resolved_staff_password
            staff_action = "created"
        elif reset_passwords or staff_password is not None:
            staff.password_hash = hash_password(resolved_staff_password)
            staff_password_out = resolved_staff_password
            staff_action = "password_updated"
        else:
            staff_password_out = "(unchanged)"
            staff_action = "exists"

        for name, pkg_minutes, price in DEFAULT_PACKAGES:
            exists = (
                await session.execute(select(Package).where(Package.name == name))
            ).scalar_one_or_none()
            if exists is None:
                session.add(Package(name=name, minutes=pkg_minutes, price_toman=price, active=True))

        tenant: Tenant | None = None
        if tenant_id is not None:
            tenant = await session.get(Tenant, tenant_id)
        if tenant is None:
            tenant = (
                await session.execute(select(Tenant).where(Tenant.name == tenant_name))
            ).scalar_one_or_none()
        if tenant is None:
            tenant = Tenant(
                name=tenant_name,
                status="active",
                price_per_minute_toman=price_per_minute,
            )
            if tenant_id is not None:
                tenant.id = tenant_id
            session.add(tenant)
            await session.flush()
            session.add(TenantBalanceCache(tenant_id=tenant.id, seconds=0, toman=0))
            await session.flush()
            tenant_action = "created"
        else:
            tenant_action = "exists"

        user = (
            await session.execute(
                select(User).where(User.email == admin_email, User.tenant_id == tenant.id)
            )
        ).scalar_one_or_none()
        if user is None:
            # Email may exist on another tenant in older installs; prefer exact match too.
            user = (
                await session.execute(select(User).where(User.email == admin_email))
            ).scalar_one_or_none()
        if user is None:
            if require_passwords_on_create and not admin_password:
                raise SystemExit("SEED_ADMIN_PASSWORD is required to create the org admin")
            session.add(
                User(
                    tenant_id=tenant.id,
                    email=admin_email,
                    password_hash=hash_password(resolved_admin_password),
                    role="org_admin",
                )
            )
            admin_password_out = resolved_admin_password
            admin_action = "created"
        elif reset_passwords or admin_password is not None:
            user.password_hash = hash_password(resolved_admin_password)
            admin_password_out = resolved_admin_password
            admin_action = "password_updated"
        else:
            admin_password_out = "(unchanged)"
            admin_action = "exists"

        if api_key:
            secret, prefix, key_hash = materialize_api_key(api_key)
            existing_key = (
                await session.execute(select(ApiKey).where(ApiKey.key_hash == key_hash))
            ).scalar_one_or_none()
            if existing_key is None:
                session.add(
                    ApiKey(
                        tenant_id=tenant.id,
                        key_hash=key_hash,
                        key_prefix=prefix,
                        label="seed",
                    )
                )
                api_key_action = "created"
            else:
                api_key_action = "exists"
            api_key_out = secret
        else:
            existing_seed = (
                await session.execute(
                    select(ApiKey).where(
                        ApiKey.tenant_id == tenant.id,
                        ApiKey.label == "seed",
                        ApiKey.revoked_at.is_(None),
                    )
                )
            ).scalar_one_or_none()
            if existing_seed is None:
                secret, prefix, key_hash = generate_api_key()
                session.add(
                    ApiKey(
                        tenant_id=tenant.id,
                        key_hash=key_hash,
                        key_prefix=prefix,
                        label="seed",
                    )
                )
                api_key_out = secret
                api_key_action = "created"
            else:
                api_key_out = f"{existing_seed.key_prefix}… (unchanged)"
                api_key_action = "exists"
        await billing.topup(
            session,
            tenant=tenant,
            minutes=minutes,
            idempotency_key=f"seed-topup:{tenant.id}:{minutes}",
        )
        tenant_id_out = tenant.id

    print("tenant_id:", tenant_id_out, f"({tenant_action})")
    print("staff:", staff_email, staff_password_out, f"({staff_action})")
    print("org_admin:", admin_email, admin_password_out, f"({admin_action})")
    print("api_key:", api_key_out, f"({api_key_action})")
    print(f"credit: {minutes} minutes")


async def _run(**kwargs: object) -> None:
    try:
        await seed(**kwargs)  # type: ignore[arg-type]
    finally:
        await dispose_engine()


def _from_env() -> dict[str, object]:
    tenant_raw = _env("SEED_TENANT_ID")
    minutes_raw = _env("SEED_MINUTES", "600") or "600"
    price_raw = _env("SEED_PRICE_PER_MINUTE", "10000") or "10000"
    reset = (_env("SEED_RESET_PASSWORDS", "false") or "false").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    return {
        "tenant_name": _env("SEED_TENANT_NAME", "شرکت نمونه") or "شرکت نمونه",
        "admin_email": _env("SEED_ADMIN_EMAIL", "admin@example.com") or "admin@example.com",
        "staff_email": _env("SEED_STAFF_EMAIL", "staff@example.com") or "staff@example.com",
        "minutes": int(minutes_raw),
        "price_per_minute": int(price_raw),
        "admin_password": _env("SEED_ADMIN_PASSWORD"),
        "staff_password": _env("SEED_STAFF_PASSWORD"),
        "reset_passwords": reset,
        "tenant_id": UUID(tenant_raw) if tenant_raw else None,
        "api_key": _env("SEED_API_KEY"),
        "require_passwords_on_create": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="seed CBI voice analytics")
    parser.add_argument(
        "--from-env",
        action="store_true",
        help="read SEED_* variables and create only missing records",
    )
    parser.add_argument("--tenant", default="شرکت نمونه")
    parser.add_argument("--tenant-id", default=None)
    parser.add_argument("--admin-email", default="admin@example.com")
    parser.add_argument("--staff-email", default="staff@example.com")
    parser.add_argument("--admin-password", default=None)
    parser.add_argument("--staff-password", default=None)
    parser.add_argument("--api-key", default=None)
    parser.add_argument(
        "--reset-passwords",
        action="store_true",
        help="overwrite passwords for existing users",
    )
    parser.add_argument("--minutes", type=int, default=600)
    parser.add_argument("--price-per-minute", type=int, default=10000)
    args = parser.parse_args()

    if args.from_env:
        if (_env("SEED_ON_DEPLOY", "true") or "true").lower() in {"0", "false", "no", "off"}:
            print("seed skipped (SEED_ON_DEPLOY=false)")
            return
        kwargs = _from_env()
    else:
        kwargs = {
            "tenant_name": args.tenant,
            "admin_email": args.admin_email,
            "staff_email": args.staff_email,
            "minutes": args.minutes,
            "price_per_minute": args.price_per_minute,
            "admin_password": args.admin_password,
            "staff_password": args.staff_password,
            "reset_passwords": args.reset_passwords,
            "tenant_id": UUID(args.tenant_id) if args.tenant_id else None,
            "api_key": args.api_key,
            "require_passwords_on_create": False,
        }
    asyncio.run(_run(**kwargs))


if __name__ == "__main__":
    main()
