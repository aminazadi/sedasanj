"""Jalase-Negar push audiences, payloads and Firebase HTTP v1 transport."""

import json
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal
from uuid import UUID

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from pydantic import AwareDatetime, BaseModel, Field, HttpUrl, StringConstraints, model_validator
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiError
from app.models import ApiKey, JalasePushInstallation, JalasePushSettings, Tenant, User
from app.services.platform_secrets import decrypt_secret

Channel = Literal["direct", "bazaar", "myket"]
Version = Annotated[
    str, StringConstraints(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9.+_-]+$")
]
Project = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]{4,62}$")]
OAUTH_URL = "https://oauth2.googleapis.com/token"


def invalid() -> ApiError:
    return ApiError("jalase_push_invalid", "فیلدها و اندازهٔ پیام پوش را بررسی کنید.")


def unavailable() -> ApiError:
    return ApiError("jalase_push_unavailable", "تنظیمات و اتصال Firebase را بررسی کنید.")


class Audience(BaseModel):
    kind: Literal["all", "organization", "user", "devices"] = "all"
    organization_id: UUID | None = None
    user_id: UUID | None = None
    device_ids: list[UUID] = Field(default_factory=list, max_length=200)
    channel: Channel | None = None
    version: Version | None = None

    @model_validator(mode="after")
    def check_target(self) -> "Audience":
        if (
            bool(self.organization_id) != (self.kind == "organization")
            or bool(self.user_id) != (self.kind == "user")
            or bool(self.device_ids) != (self.kind == "devices")
        ):
            raise invalid()
        return self


class Message(BaseModel):
    kind: Literal["notification", "combined", "data"]
    title: str = Field(default="", max_length=180)
    body: str = Field(default="", max_length=2000)
    image: HttpUrl | None = None
    destination: Literal["home", "guide", "people", "settings", "models"] = "home"
    sound: bool = True
    replace: bool = False
    data: dict[str, Any] = Field(default_factory=dict)
    priority: Literal["normal", "high"] = "normal"
    ttl: int = Field(default=3600, ge=60, le=2419200)

    @model_validator(mode="after")
    def check_payload(self) -> "Message":
        if (
            (self.kind != "data" and not (self.title.strip() and self.body.strip()))
            or (self.kind == "data" and (not self.data or self.priority != "normal"))
            or (self.kind == "notification" and self.data)
            or (self.image and (self.image.scheme != "https" or self.image.username is not None))
        ):
            raise invalid()
        try:
            content = envelope(self, UUID(int=0), self.ttl)
            body = content["data"]["payload"]
            if r"\u0000" in body:
                raise ValueError
            size = len(json.dumps(content, ensure_ascii=False, allow_nan=False).encode())
        except (ValueError, RecursionError, UnicodeError):
            raise invalid() from None
        if size > 4096:
            raise invalid()
        return self


class Compose(BaseModel):
    audience: Audience
    message: Message
    scheduled_at: AwareDatetime | None = None


class Send(Compose):
    id: UUID
    confirmed_all: bool = False


class TestSend(BaseModel):
    id: UUID
    installation_id: UUID
    message: Message


def envelope(
    message: Message, campaign_id: UUID, ttl: int, *, targeted: bool = False
) -> dict[str, Any]:
    # Keep all notification rendering in the app, including silent channels and deduplication.
    data = {"campaign_id": str(campaign_id)}
    if not targeted:
        payload = message.model_dump(mode="json", exclude={"priority", "ttl"})
        data["payload"] = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    android = {"ttl": f"{ttl}s", "priority": message.priority}
    # A shared Android notification tag replaces a visible announcement, not queued FCM messages.
    return {"data": data, "android": android}


def recipients(audience: Audience, now: datetime) -> Any:
    device = JalasePushInstallation
    query = select(device).where(
        device.enabled.is_(True), device.seen_at >= now - timedelta(days=30)
    )
    if audience.kind in ("organization", "user"):
        query = (
            query.join(ApiKey, ApiKey.id == device.mobile_key_id)
            .join(User, and_(User.id == ApiKey.user_id, User.tenant_id == ApiKey.tenant_id))
            .join(Tenant, Tenant.id == ApiKey.tenant_id)
            .where(
                ApiKey.kind == "mobile",
                ApiKey.revoked_at.is_(None),
                or_(ApiKey.expires_at.is_(None), ApiKey.expires_at > now),
                Tenant.status == "active",
            )
        )
        if audience.kind == "organization":
            query = query.where(ApiKey.tenant_id == audience.organization_id)
        else:
            query = query.where(User.id == audience.user_id)
    if audience.kind == "devices":
        query = query.where(device.id.in_(audience.device_ids))
    if audience.version:
        query = query.where(device.version == audience.version)
    if audience.channel:
        query = query.where(device.channel == audience.channel)
    return query


async def settings(session: AsyncSession) -> JalasePushSettings | None:
    return await session.get(JalasePushSettings, 1)


def credentials_json(raw: str, project: str) -> dict[str, str]:
    try:
        obj = json.loads(raw)
        if not isinstance(obj, dict):
            raise ValueError
        email, key = obj.get("client_email"), obj.get("private_key")
        if (
            obj.get("type") != "service_account"
            or obj.get("project_id") != project
            or not isinstance(email, str)
            or not email.endswith(".iam.gserviceaccount.com")
            or not isinstance(key, str)
            or not isinstance(load_pem_private_key(key.encode(), password=None), RSAPrivateKey)
        ):
            raise ValueError
    except (ValueError, TypeError, RecursionError):
        raise unavailable() from None
    return {"client_email": email, "private_key": key}


class Firebase:
    def __init__(self, client: httpx.AsyncClient, config: JalasePushSettings) -> None:
        if not config.credentials:
            raise unavailable()
        self.client = client
        self.project = config.project
        self.credentials = credentials_json(decrypt_secret(config.credentials), self.project)
        self.access_token: str | None = None

    async def authenticate(self) -> None:
        now = datetime.now(UTC)
        assertion = jwt.encode(
            {
                "iss": self.credentials["client_email"],
                "scope": "https://www.googleapis.com/auth/firebase.messaging",
                "aud": OAUTH_URL,
                "iat": now,
                "exp": now + timedelta(minutes=5),
            },
            self.credentials["private_key"],
            algorithm="RS256",
        )
        response = await self.client.post(
            OAUTH_URL,
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": assertion,
            },
        )
        if not response.is_success:
            raise unavailable()
        token = response.json().get("access_token")
        if not isinstance(token, str) or not token:
            raise unavailable()
        self.access_token = token

    async def send(self, message: dict[str, Any], *, validate_only: bool = False) -> httpx.Response:
        return await self.client.post(
            f"https://fcm.googleapis.com/v1/projects/{self.project}/messages:send",
            headers={"Authorization": f"Bearer {self.access_token}"},
            json={"message": message, "validate_only": validate_only},
        )
