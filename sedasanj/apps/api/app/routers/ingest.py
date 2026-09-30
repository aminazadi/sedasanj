from __future__ import annotations

import asyncio
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal, cast
from uuid import UUID

from fastapi import APIRouter, File, Form, Header, Response, UploadFile, status

from app.config import get_settings
from app.db import control_session_scope
from app.deps import ApiKeyDep, ApiKeySession
from app.errors import ApiError
from app.models import ApiKey, Tenant
from app.schemas import IngestAccepted, IngestConfigValidation
from app.security import verify_password
from app.services import billing
from app.services.archives import prepare_agent_audio
from app.services.ingest import accept_upload

router = APIRouter(prefix="/v1/ingest", tags=["ingest"])


async def _control_api_key(key_id: UUID) -> ApiKey:
    async with control_session_scope() as control:
        api_key = await control.get(ApiKey, key_id)
        if api_key is None or api_key.revoked_at is not None:
            raise ApiError("unauthorized", "API key no longer exists")
        return api_key


@router.get("/health")
async def ingest_health(principal: ApiKeyDep, session: ApiKeySession) -> dict[str, object]:
    """Connectivity + key check used by the agent and the install page (§11)."""
    assert principal.tenant_id is not None
    tenant = await session.get(Tenant, principal.tenant_id)
    balance = await billing.get_balance(session, principal.tenant_id)
    api_key = await _control_api_key(principal.id)
    return {
        "status": "ok",
        "tenant": tenant.name if tenant else None,
        "tenant_id": str(principal.tenant_id),
        "balance_seconds": balance.seconds,
        "balance_minutes": round(balance.seconds / 60, 1),
        "server_time": datetime.now(UTC).isoformat(),
        "archive_format": api_key.archive_format if api_key else None,
        "archive_password_configured": bool(api_key and api_key.archive_password_hash),
    }


async def _validate_archive_password(api_key: ApiKey, archive_password: str | None) -> bool:
    password_configured = api_key.archive_password_hash is not None
    if password_configured:
        if not archive_password:
            raise ApiError("archive_password_required", "zip password is required")
        valid_password = await asyncio.to_thread(
            verify_password, api_key.archive_password_hash or "", archive_password
        )
        if not valid_password:
            raise ApiError("archive_password_invalid", "zip password is invalid")
        return True
    if archive_password:
        raise ApiError("archive_password_invalid", "this API key has no archive password")
    return True


@router.post("/config/validate", response_model=IngestConfigValidation)
async def validate_ingest_config(
    principal: ApiKeyDep,
    session: ApiKeySession,
    archive_password: Annotated[str | None, Header(alias="X-CBI-Archive-Password")] = None,
) -> IngestConfigValidation:
    """Validate an agent's API key, archive mode, and optional ZIP password."""
    assert principal.tenant_id is not None
    tenant = await session.get(Tenant, principal.tenant_id)
    api_key = await _control_api_key(principal.id)
    await _validate_archive_password(api_key, archive_password)
    balance = await billing.get_balance(session, principal.tenant_id)
    return IngestConfigValidation(
        tenant=tenant.name if tenant else None,
        tenant_id=principal.tenant_id,
        balance_seconds=balance.seconds,
        balance_minutes=round(balance.seconds / 60, 1),
        server_time=datetime.now(UTC),
        archive_format=cast(Literal["wav", "gzip", "zip"], api_key.archive_format),
        archive_password_configured=api_key.archive_password_hash is not None,
        archive_password_valid=True,
    )


@router.post("/calls", response_model=IngestAccepted, status_code=status.HTTP_201_CREATED)
async def ingest_call(
    principal: ApiKeyDep,
    response: Response,
    session: ApiKeySession,
    file: Annotated[UploadFile, File()],
    asterisk_uniqueid: Annotated[str, Form()],
    caller_number: Annotated[str, Form()],
    dialed_number: Annotated[str, Form()],
    started_at: Annotated[datetime, Form()],
    ended_at: Annotated[datetime, Form()],
    direction: Annotated[str | None, Form()] = None,
    agent_extension: Annotated[str | None, Form()] = None,
    campaign_id: Annotated[str | None, Form()] = None,
    source: Annotated[str | None, Form()] = None,
    external_reference: Annotated[str | None, Form()] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    archive_password: Annotated[str | None, Header(alias="X-CBI-Archive-Password")] = None,
) -> IngestAccepted:
    """Upload one call archive, validate its WAV, reserve credit, store it, and queue ASR.

    The API key selects WAV (legacy), GZIP, or ZIP. ZIP may require an AES-256 password in
    `X-CBI-Archive-Password`. The archive must contain exactly one root-level PCM WAV. Reusing
    the same Asterisk unique ID returns the original call.
    """
    tenant_id = principal.tenant_id
    assert tenant_id is not None
    unique_id = asterisk_uniqueid.strip()
    if not unique_id:
        raise ApiError("invalid_request", "asterisk_uniqueid is required")

    api_key = await _control_api_key(principal.id)
    password_configured = api_key.archive_password_hash is not None
    await _validate_archive_password(api_key, archive_password)

    with tempfile.TemporaryDirectory(prefix="cbi-ingest-") as tmp:
        audio_path = await prepare_agent_audio(
            file,
            api_key.archive_format,
            archive_password,
            password_configured,
            Path(tmp),
            get_settings(),
        )
        result = await accept_upload(
            tenant_id=tenant_id,
            payload=audio_path,
            asterisk_uniqueid=unique_id,
            caller_number=caller_number,
            dialed_number=dialed_number,
            started_at=started_at,
            ended_at=ended_at,
            direction=direction,
            agent_extension=agent_extension,
            campaign_id=campaign_id,
            source=source,
            external_reference=external_reference,
            idempotency_key=idempotency_key,
        )
    if result.replayed:
        response.status_code = status.HTTP_200_OK
    return result.accepted
