"""Speaker profiles: the people a Jalase-Negar user defined and the voiceprints of their voices.

The app computes embeddings on the phone and syncs them here so a new or re-paired phone gets
them back at once. This module owns the rules:

* A profile belongs to one user. `private` profiles are seen by that user only; `org` profiles are
  readable (never editable) by every paired phone of the tenant.
* `version` is an optimistic lock. A retried request that is already applied is a replay, not a
  conflict; a request based on an older version is a conflict and carries the server's state.
* Voiceprint samples only ever accumulate or are removed by id; two phones that each added a
  sample both keep it.
* A voiceprint needs recorded consent. Deleting a profile drops its voiceprints and name at once;
  an empty tombstone stays long enough for other phones to hear about it.
* `change_seq` comes from a per-tenant counter whose row lock lasts to the commit, so counter order
  is commit order and a client that has read up to N has seen everything committed up to N.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import and_, delete, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.errors import ApiError
from app.models import SpeakerProfile, SpeakerSyncState, SpeakerVoiceprint
from app.schemas import (
    SpeakerChangesOut,
    SpeakerProfileOut,
    SpeakerProfilePut,
    SpeakerVoiceprintOut,
)
from app.services import voiceprint_crypto as crypto

logger = logging.getLogger(__name__)

DELETED_NAME = "—"
MAX_CONSENT_AHEAD = timedelta(minutes=5)


@dataclass(frozen=True)
class PutResult:
    profile: SpeakerProfile
    out: SpeakerProfileOut
    created: bool
    changed: bool


def not_found() -> ApiError:
    return ApiError(
        "speaker_profile_not_found",
        "این فرد روی سرور پیدا نشد؛ فهرست افراد را تازه کنید و دوباره تلاش کنید",
    )


def storage_unavailable() -> ApiError:
    return ApiError(
        "speaker_storage_unavailable",
        "ذخیره‌ی امن ردصدا روی سرور آماده نیست؛ چند دقیقه بعد دوباره تلاش کنید "
        "و اگر ادامه داشت به مدیر صداسنج اطلاع دهید",
    )


def _decrypt(row: SpeakerVoiceprint) -> bytes:
    try:
        return crypto.decrypt_embedding(row.id, row.embedding)
    except crypto.VoiceprintStorageError as exc:
        logger.error("speaker_voiceprint_unreadable profile_id=%s", row.profile_id)
        raise storage_unavailable() from exc


def _voiceprint_out(row: SpeakerVoiceprint) -> SpeakerVoiceprintOut:
    return SpeakerVoiceprintOut(
        client_id=row.client_id,
        model_id=row.model_id,
        model_version=row.model_version,
        dim=row.dim,
        embedding_b64=crypto.encode_embedding(_decrypt(row)),
        quality=row.quality,
        duration_ms=row.duration_ms,
    )


def _profile_out(
    profile: SpeakerProfile, voiceprints: list[SpeakerVoiceprint], *, mine: bool
) -> SpeakerProfileOut:
    gone = profile.deleted_at is not None
    visible = not gone and (mine or profile.visibility == "org")
    return SpeakerProfileOut(
        client_id=profile.client_id,
        display_name=profile.display_name if visible else "",
        visibility=profile.visibility if visible else "private",  # type: ignore[arg-type]
        version=profile.version,
        change_seq=profile.change_seq,
        deleted=not visible,
        mine=mine,
        consent_at=profile.consent_at if visible else None,
        consent_version=profile.consent_version if visible else None,
        updated_at=profile.updated_at,
        voiceprints=[_voiceprint_out(row) for row in voiceprints] if visible else [],
    )


async def _next_seq(session: AsyncSession, tenant_id: UUID) -> int:
    """Next change number; the counter row stays locked until this transaction ends."""
    result = await session.execute(
        text(
            "INSERT INTO speaker_sync_state (tenant_id, seq) VALUES (:tenant, 1) "
            "ON CONFLICT (tenant_id) DO UPDATE SET seq = speaker_sync_state.seq + 1 "
            "RETURNING seq"
        ),
        {"tenant": tenant_id},
    )
    return int(result.scalar_one())


async def _load(
    session: AsyncSession, tenant_id: UUID, client_id: UUID, *, lock: bool = False
) -> SpeakerProfile | None:
    stmt = select(SpeakerProfile).where(
        SpeakerProfile.tenant_id == tenant_id, SpeakerProfile.client_id == client_id
    )
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    return (await session.execute(stmt)).scalar_one_or_none()


async def _voiceprint_rows(
    session: AsyncSession, profile_ids: list[UUID]
) -> dict[UUID, list[SpeakerVoiceprint]]:
    grouped: dict[UUID, list[SpeakerVoiceprint]] = {profile_id: [] for profile_id in profile_ids}
    if not profile_ids:
        return grouped
    rows = (
        (
            await session.execute(
                select(SpeakerVoiceprint)
                .where(SpeakerVoiceprint.profile_id.in_(profile_ids))
                .order_by(SpeakerVoiceprint.created_at, SpeakerVoiceprint.id)
            )
        )
        .scalars()
        .all()
    )
    for row in rows:
        grouped[row.profile_id].append(row)
    return grouped


async def profile_out(
    session: AsyncSession, profile: SpeakerProfile, user_id: UUID
) -> SpeakerProfileOut:
    rows = (await _voiceprint_rows(session, [profile.id]))[profile.id]
    return _profile_out(profile, rows, mine=profile.owner_user_id == user_id)


def _conflict(current: SpeakerProfileOut) -> ApiError:
    return ApiError(
        "speaker_profile_conflict",
        "این فرد روی دستگاه دیگری تغییر کرده است؛ تغییرات را با نسخه‌ی سرور ادغام کنید "
        "و دوباره بفرستید",
        extra={"current": current.model_dump(mode="json")},
    )


def _check_consent(profile: SpeakerProfile | None, payload: SpeakerProfilePut) -> None:
    if payload.consent is not None and payload.consent.at > datetime.now(UTC) + MAX_CONSENT_AHEAD:
        raise ApiError(
            "speaker_consent_required",
            "زمان ثبت رضایت‌نامه معتبر نیست؛ تاریخ و ساعت گوشی را درست کنید و دوباره تلاش کنید",
        )
    if not payload.voiceprints:
        return
    if payload.consent is None and (profile is None or profile.consent_at is None):
        raise ApiError(
            "speaker_consent_required",
            "برای ذخیره‌ی ردصدا باید رضایت صریح همین فرد ثبت شود؛ "
            "در اپ مرحله‌ی رضایت‌نامه را کامل کنید",
        )


def _decode_new(payload: SpeakerProfilePut) -> dict[tuple[UUID, str], bytes]:
    decoded: dict[tuple[UUID, str], bytes] = {}
    for item in payload.voiceprints:
        key = (item.client_id, item.model_id)
        if key in decoded:
            raise ApiError(
                "speaker_voiceprint_invalid",
                "یک نمونه‌ی صدا دو بار در درخواست آمده؛ اپ را به‌روز کنید و دوباره بفرستید",
            )
        try:
            decoded[key] = crypto.decode_embedding(item.embedding_b64, item.dim)
        except crypto.VoiceprintInvalid as exc:
            raise ApiError(
                "speaker_voiceprint_invalid",
                "ردصدای ارسالی معتبر نیست؛ نمونه‌ی صدا را در اپ دوباره ضبط کنید",
            ) from exc
    return decoded


async def put_profile(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    client_id: UUID,
    payload: SpeakerProfilePut,
) -> PutResult:
    """Create or update the caller's profile; idempotent for a request that is already applied."""
    settings = get_settings()
    if (payload.voiceprints or payload.remove_voiceprints) and crypto.storage_error():
        raise storage_unavailable()
    new_samples = _decode_new(payload)
    profile = await _load(session, tenant_id, client_id, lock=True)
    created = profile is None
    if profile is not None and (profile.owner_user_id != user_id or profile.deleted_at):
        raise not_found()
    if profile is None and payload.base_version != 0:
        raise not_found()
    _check_consent(profile, payload)

    existing: list[SpeakerVoiceprint] = []
    if profile is not None:
        existing = (await _voiceprint_rows(session, [profile.id]))[profile.id]
    by_key = {(row.client_id, row.model_id): row for row in existing}

    additions = []
    updates = []
    for item in payload.voiceprints:
        raw = new_samples[(item.client_id, item.model_id)]
        row = by_key.get((item.client_id, item.model_id))
        if row is None:
            additions.append((item, raw))
        elif _decrypt(row) != raw or row.model_version != item.model_version or row.dim != item.dim:
            updates.append((row, item, raw))
    removed_ids = set(payload.remove_voiceprints)
    removals = [row for row in existing if row.client_id in removed_ids]
    if (
        len(existing) - len(removals) + len(additions)
        > settings.speaker_max_voiceprints_per_profile
    ):
        raise ApiError(
            "speaker_profile_limit",
            "تعداد نمونه‌های صدای این فرد به سقف رسیده است؛ نمونه‌های قدیمی را حذف کنید",
        )

    consent_changed = bool(
        payload.consent is not None
        and (
            profile is None
            or profile.consent_at is None
            or payload.consent.at > profile.consent_at
            or payload.consent.version != profile.consent_version
        )
    )
    changed = (
        created
        or payload.display_name != profile.display_name  # type: ignore[union-attr]
        or payload.visibility != profile.visibility  # type: ignore[union-attr]
        or consent_changed
        or bool(additions or updates or removals)
    )

    if profile is not None:
        if payload.base_version != profile.version:
            current = _profile_out(profile, existing, mine=True)
            if not changed:
                return PutResult(profile, current, created=False, changed=False)
            raise _conflict(current)
        if not changed:
            return PutResult(
                profile, _profile_out(profile, existing, mine=True), created=False, changed=False
            )

    if created:
        active = (
            await session.execute(
                select(SpeakerProfile.id).where(
                    SpeakerProfile.tenant_id == tenant_id,
                    SpeakerProfile.owner_user_id == user_id,
                    SpeakerProfile.deleted_at.is_(None),
                )
            )
        ).all()
        if len(active) >= settings.speaker_max_profiles_per_user:
            raise ApiError(
                "speaker_profile_limit",
                "تعداد افراد تعریف‌شده به سقف رسیده است؛ افراد بی‌استفاده را حذف کنید",
            )
        profile = SpeakerProfile(
            tenant_id=tenant_id,
            owner_user_id=user_id,
            client_id=client_id,
            display_name=payload.display_name,
            visibility=payload.visibility,
            was_shared=payload.visibility == "org",
            version=1,
            change_seq=0,
        )
        session.add(profile)
    assert profile is not None

    now = datetime.now(UTC)
    profile.display_name = payload.display_name
    profile.visibility = payload.visibility
    profile.was_shared = profile.was_shared or payload.visibility == "org"
    if payload.consent is not None:
        profile.consent_at = payload.consent.at
        profile.consent_version = payload.consent.version
    if not created:
        profile.version += 1
    profile.updated_at = now
    await session.flush()

    for row in removals:
        await session.delete(row)
    for row, item, raw in updates:
        row.model_version = item.model_version
        row.dim = item.dim
        row.embedding = crypto.encrypt_embedding(row.id, raw)
        row.quality = item.quality
        row.duration_ms = item.duration_ms
    for item, raw in additions:
        sample_id = uuid4()
        session.add(
            SpeakerVoiceprint(
                id=sample_id,
                tenant_id=tenant_id,
                profile_id=profile.id,
                client_id=item.client_id,
                model_id=item.model_id,
                model_version=item.model_version,
                dim=item.dim,
                embedding=crypto.encrypt_embedding(sample_id, raw),
                quality=item.quality,
                duration_ms=item.duration_ms,
            )
        )
    profile.change_seq = await _next_seq(session, tenant_id)
    await session.flush()
    out = await profile_out(session, profile, user_id)
    return PutResult(profile, out, created=created, changed=True)


async def delete_profile(
    session: AsyncSession, *, tenant_id: UUID, user_id: UUID, client_id: UUID
) -> tuple[SpeakerProfile, bool]:
    """Forget a person: voiceprints and name go now, an empty tombstone tells other phones."""
    profile = await _load(session, tenant_id, client_id, lock=True)
    if profile is None or profile.owner_user_id != user_id:
        raise not_found()
    if profile.deleted_at is not None:
        return profile, False
    await session.execute(
        delete(SpeakerVoiceprint).where(SpeakerVoiceprint.profile_id == profile.id)
    )
    now = datetime.now(UTC)
    profile.deleted_at = now
    profile.display_name = DELETED_NAME
    profile.consent_at = None
    profile.consent_version = None
    profile.version += 1
    profile.updated_at = now
    profile.change_seq = await _next_seq(session, tenant_id)
    await session.flush()
    return profile, True


async def list_changes(
    session: AsyncSession, *, tenant_id: UUID, user_id: UUID, cursor: int, limit: int
) -> SpeakerChangesOut:
    """Profiles changed after `cursor` that this user may know about, oldest change first."""
    shared_or_mine = or_(
        SpeakerProfile.owner_user_id == user_id,
        and_(SpeakerProfile.visibility == "org", SpeakerProfile.deleted_at.is_(None)),
        # Was shared once: colleagues get an empty entry when it stops being visible.
        SpeakerProfile.was_shared.is_(True),
    )
    rows = (
        (
            await session.execute(
                select(SpeakerProfile)
                .where(
                    SpeakerProfile.tenant_id == tenant_id,
                    SpeakerProfile.change_seq > cursor,
                    shared_or_mine,
                )
                .order_by(SpeakerProfile.change_seq)
                .limit(limit + 1)
            )
        )
        .scalars()
        .all()
    )
    has_more = len(rows) > limit
    page = list(rows[:limit])
    voiceprints = await _voiceprint_rows(
        session, [row.id for row in page if row.deleted_at is None]
    )
    items = [
        _profile_out(row, voiceprints.get(row.id, []), mine=row.owner_user_id == user_id)
        for row in page
    ]
    if has_more:
        next_cursor = page[-1].change_seq
    else:
        # Counter order is commit order, so everything up to the committed counter has been seen
        # even when the newest changes were not visible to this user.
        state = await session.get(SpeakerSyncState, tenant_id)
        next_cursor = max(cursor, state.seq if state else 0, page[-1].change_seq if page else 0)
    return SpeakerChangesOut(items=items, next_cursor=next_cursor, has_more=has_more)


async def resolve_profile_ids(
    session: AsyncSession, *, tenant_id: UUID, user_id: UUID, client_ids: set[UUID]
) -> dict[UUID, UUID]:
    """Map app-side profile ids to server ids for profiles this user may reference."""
    if not client_ids:
        return {}
    rows = (
        (
            await session.execute(
                select(SpeakerProfile.client_id, SpeakerProfile.id).where(
                    SpeakerProfile.tenant_id == tenant_id,
                    SpeakerProfile.client_id.in_(client_ids),
                    SpeakerProfile.deleted_at.is_(None),
                    or_(
                        SpeakerProfile.owner_user_id == user_id, SpeakerProfile.visibility == "org"
                    ),
                )
            )
        )
        .tuples()
        .all()
    )
    return dict(rows)


async def purge_tombstones(session: AsyncSession, tenant_id: UUID) -> int:
    """Drop deleted profiles that every phone has had ample time to hear about."""
    cutoff = datetime.now(UTC) - timedelta(days=get_settings().speaker_tombstone_days)
    result = await session.execute(
        delete(SpeakerProfile).where(
            SpeakerProfile.tenant_id == tenant_id,
            SpeakerProfile.deleted_at.is_not(None),
            SpeakerProfile.deleted_at < cutoff,
        )
    )
    return int(getattr(result, "rowcount", 0) or 0)
