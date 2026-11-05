from __future__ import annotations

import asyncio
import smtplib
import ssl
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from typing import Literal
from urllib.parse import unquote, urlsplit
from uuid import UUID, uuid4

import jwt
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.errors import ApiError
from app.models import RefreshToken, Tenant, User
from app.security import JWT_ALGORITHM, hash_refresh_token

Action = Literal["email", "password"]
LIFETIME = timedelta(minutes=30)


def _prefix(action: Action) -> str:
    return f"member-account:{action}:"


def _send(settings: Settings, recipient: str, action: Action, token: str) -> None:
    if not settings.smtp_url:
        raise ValueError("SMTP is not configured")
    url = urlsplit(settings.smtp_url)
    if url.scheme not in {"smtp", "smtps"} or not url.hostname:
        raise ValueError("invalid SMTP configuration")
    context = ssl.create_default_context()
    message = EmailMessage()
    message["From"] = settings.notify_from_email
    message["To"] = recipient
    message["Subject"] = (
        "تأیید ایمیل جدید صداسنج" if action == "email" else "بازنشانی گذرواژهٔ صداسنج"
    )
    link = f"{settings.public_app_url.rstrip('/')}/account-action#{action}={token}"
    message.set_content(
        f"برای ادامه، پیوند زیر را باز کنید. پیوند تا ۳۰ دقیقه معتبر است.\n\n{link}"
    )

    client: smtplib.SMTP
    if url.scheme == "smtps":
        client = smtplib.SMTP_SSL(url.hostname, url.port or 465, timeout=10, context=context)
    else:
        client = smtplib.SMTP(url.hostname, url.port or 587, timeout=10)
    with client:
        if url.scheme == "smtp":
            client.starttls(context=context)
        if url.username is not None and url.password is not None:
            client.login(unquote(url.username), unquote(url.password))
        client.send_message(message)


async def issue(
    session: AsyncSession, user: User, actor_id: UUID, action: Action, recipient: str
) -> None:
    settings = get_settings()
    now = datetime.now(UTC)
    expires_at = now + LIFETIME
    token = jwt.encode(
        {
            "typ": _prefix(action),
            "sub": str(user.id),
            "actor_id": str(actor_id),
            "email": user.email,
            "recipient": recipient,
            "exp": expires_at,
            "jti": str(uuid4()),
        },
        settings.jwt_secret,
        algorithm=JWT_ALGORITHM,
    )
    await session.execute(
        update(RefreshToken)
        .where(
            RefreshToken.user_id == user.id,
            RefreshToken.token_hash.startswith(_prefix(action)),
            RefreshToken.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    # The namespaced digest cannot match the ordinary refresh endpoint's SHA-256 digest.
    session.add(
        RefreshToken(
            user_id=user.id,
            token_hash=_prefix(action) + hash_refresh_token(token),
            expires_at=expires_at,
        )
    )
    await session.flush()
    try:
        await asyncio.to_thread(_send, settings, recipient, action, token)
    except (ValueError, OSError, smtplib.SMTPException):
        raise ApiError(
            "member_account_email_unavailable",
            "ارسال ایمیل ممکن نشد. تنظیمات ارسال ایمیل را بررسی کنید و دوباره تلاش کنید.",
        ) from None


async def consume(session: AsyncSession, action: Action, token: str) -> tuple[User, UUID, str]:
    invalid = ApiError(
        "member_account_link_invalid",
        "پیوند نامعتبر یا منقضی شده است. از مدیر سازمان بخواهید پیوند تازه‌ای بفرستد.",
    )
    try:
        claims = jwt.decode(token, get_settings().jwt_secret, algorithms=[JWT_ALGORITHM])
        if claims["typ"] != _prefix(action):
            raise invalid
        user_id = UUID(claims["sub"])
        actor_id = UUID(claims["actor_id"])
        recipient: str = claims["recipient"]
    except (jwt.PyJWTError, KeyError, ValueError, TypeError, AttributeError):
        raise invalid from None

    user = await session.get(User, user_id, with_for_update=True)
    if user is None or user.email != claims.get("email"):
        raise invalid
    actor = await session.get(User, actor_id)
    tenant = await session.get(Tenant, user.tenant_id)
    if (
        actor is None
        or actor.tenant_id != user.tenant_id
        or actor.role != "org_admin"
        or tenant is None
        or tenant.status != "active"
        or (action == "email" and user.role == "org_admin")
    ):
        raise invalid
    now = datetime.now(UTC)
    link = await session.scalar(
        select(RefreshToken)
        .where(
            RefreshToken.user_id == user_id,
            RefreshToken.token_hash == _prefix(action) + hash_refresh_token(token),
            RefreshToken.revoked_at.is_(None),
            RefreshToken.expires_at > now,
        )
        .with_for_update()
    )
    if link is None:
        raise invalid
    link.revoked_at = now
    return user, actor_id, recipient
