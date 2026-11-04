"""Speaker profiles sync for the Jalase-Negar app: people and their voiceprints.

Only paired phones (personal mobile tokens) reach these routes. They carry biometric data, so the
`meetings` tag keeps them out of the public API description, and nothing here logs a name, an
embedding or a request body.
"""

from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.db import session_scope
from app.deps import MeetingsKeyDep, client_ip
from app.schemas import SpeakerChangesOut, SpeakerProfileOut, SpeakerProfilePut
from app.services import audit, ratelimit, speaker_profiles

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/meetings/speaker-profiles", tags=["meetings"])


async def _throttle(principal: MeetingsKeyDep) -> None:
    await ratelimit.enforce(
        f"speaker-sync:{principal.id}", get_settings().rate_limit_speaker_sync_per_minute
    )


@router.get("/changes", response_model=SpeakerChangesOut)
async def speaker_changes(
    principal: MeetingsKeyDep,
    cursor: Annotated[int, Query(ge=0, le=9_000_000_000_000_000)] = 0,
    limit: Annotated[int | None, Query(ge=1, le=500)] = None,
) -> SpeakerChangesOut:
    """Profiles changed after `cursor`; page until `has_more` is false, keep `next_cursor`.

    Pass 0 to fetch everything, as a newly paired phone does. A deleted or no-longer-shared
    profile arrives as an entry with `deleted: true` and no name or voiceprints.
    """
    assert principal.tenant_id is not None and principal.user_id is not None
    await _throttle(principal)
    async with session_scope(principal.tenant_id) as session:
        return await speaker_profiles.list_changes(
            session,
            tenant_id=principal.tenant_id,
            user_id=principal.user_id,
            cursor=cursor,
            limit=limit or get_settings().speaker_sync_page_size,
        )


@router.put("/{client_id}", response_model=SpeakerProfileOut)
async def put_speaker_profile(
    client_id: UUID, payload: SpeakerProfilePut, request: Request, principal: MeetingsKeyDep
) -> SpeakerProfileOut:
    """Create (`base_version` 0) or update the caller's profile.

    Voiceprint samples are merged by id: sending a sample again is harmless, a sample missing
    from the request is kept unless listed in `remove_voiceprints`. A stale `base_version` gets
    409 `speaker_profile_conflict` with the server's current state under `current`.
    """
    assert principal.tenant_id is not None and principal.user_id is not None
    await _throttle(principal)
    for attempt in (1, 2):
        try:
            async with session_scope(principal.tenant_id) as session:
                result = await speaker_profiles.put_profile(
                    session,
                    tenant_id=principal.tenant_id,
                    user_id=principal.user_id,
                    client_id=client_id,
                    payload=payload,
                )
                if result.changed:
                    await audit.record(
                        session,
                        actor_type="api_key",
                        actor_id=principal.id,
                        tenant_id=principal.tenant_id,
                        action="speaker.create" if result.created else "speaker.update",
                        payload={
                            "profile_id": str(result.profile.id),
                            "visibility": result.profile.visibility,
                            "voiceprints": len(payload.voiceprints),
                        },
                        ip=client_ip(request),
                    )
            return result.out
        except IntegrityError:
            # Two first requests for the same new profile raced; the second now updates it.
            if attempt == 2:
                raise
    raise AssertionError("unreachable")  # pragma: no cover


@router.delete("/{client_id}", response_model=SpeakerProfileOut)
async def delete_speaker_profile(
    client_id: UUID, request: Request, principal: MeetingsKeyDep
) -> SpeakerProfileOut:
    """Forget a person on every phone: the voiceprints and name are erased right away."""
    assert principal.tenant_id is not None and principal.user_id is not None
    await _throttle(principal)
    async with session_scope(principal.tenant_id) as session:
        profile, erased = await speaker_profiles.delete_profile(
            session,
            tenant_id=principal.tenant_id,
            user_id=principal.user_id,
            client_id=client_id,
        )
        if erased:
            await audit.record(
                session,
                actor_type="api_key",
                actor_id=principal.id,
                tenant_id=principal.tenant_id,
                action="speaker.delete",
                payload={"profile_id": str(profile.id)},
                ip=client_ip(request),
            )
        return await speaker_profiles.profile_out(session, profile, principal.user_id)
