from __future__ import annotations

import re

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiError
from app.models import Tenant, User
from app.services.phone_numbers import normalize_call_number


def normalize_mobile(value: str) -> str:
    mobile = normalize_call_number(value)
    if not re.fullmatch(r"09[0-9]{9}", mobile):
        raise ApiError("invalid_request", "شماره موبایل معتبر نیست.")
    return mobile


async def mobile_lock(session: AsyncSession, mobile: str) -> None:
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"phone:{mobile}"},
    )


async def mobile_accounts(session: AsyncSession, mobile: str) -> list[tuple[User, Tenant]]:
    digits = func.regexp_replace(
        func.translate(User.mobile_number, "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"),
        "[^0-9]",
        "",
        "g",
    )
    rows = (
        await session.execute(
            select(User, Tenant)
            .join(Tenant, User.tenant_id == Tenant.id)
            .where(
                digits.in_([mobile, mobile[1:], "98" + mobile[1:], "0098" + mobile[1:]]),
                Tenant.status != "deleted",
            )
            .order_by(User.created_at)
        )
    ).all()
    return [(user, tenant) for user, tenant in rows]
