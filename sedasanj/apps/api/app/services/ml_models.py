"""ML model registry: storage keys, retention rules and the periodic sweeper.

Artifacts live under ``ml-models/`` in the main bucket. A row goes ``uploading`` -> ``ready``;
the file is deleted (row kept as metadata, status ``deleted``) when a newer version replaces it.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select

from app.config import get_settings
from app.db import control_session_scope
from app.models import MlModelRelease
from app.services.storage import get_storage

logger = logging.getLogger(__name__)

KEY_PREFIX = "ml-models/"
ONNX_MIME = "application/octet-stream"
# A serialized ONNX ModelProto starts with the field-1 (ir_version) varint tag.
ONNX_FIRST_BYTE = 0x08
RETIRING_STATUSES = ("ready",)


def artifact_key(release_id: UUID, kind: str, version: str) -> str:
    return f"{KEY_PREFIX}{kind}/{release_id}/{kind}-{version}.onnx"


def release_id_from_key(key: str) -> UUID | None:
    parts = key.split("/")
    if len(parts) != 4 or parts[0] + "/" != KEY_PREFIX:
        return None
    try:
        return UUID(parts[2])
    except ValueError:
        return None


def orphan_keys(
    stored: Sequence[tuple[str, datetime]],
    live_ids: set[UUID],
    *,
    now: datetime | None = None,
) -> list[str]:
    """Stored keys that no live row refers to, once the safe grace period has passed."""
    cutoff = (now or datetime.now(UTC)) - timedelta(
        minutes=get_settings().ml_model_orphan_grace_minutes
    )
    return [
        key
        for key, modified in stored
        if (release_id := release_id_from_key(key)) is not None
        and release_id not in live_ids
        and modified < cutoff
    ]


def retention_expired(row: MlModelRelease, *, now: datetime) -> bool:
    """A superseded, unpinned champion whose retention window has passed."""
    if row.channel != "champion" or row.status != "ready" or row.pinned:
        return False
    if row.superseded_at is None:
        return False
    hours = get_settings().ml_model_prev_retention_hours
    return row.superseded_at + timedelta(hours=hours) <= now


async def delete_keys(keys: Sequence[str]) -> None:
    """Best effort: the sweeper removes whatever a failed delete leaves behind."""
    storage = get_storage()
    for key in keys:
        try:
            await storage.delete(key)
        except Exception:  # noqa: BLE001
            logger.warning("ml_model_delete_deferred key=%s", key)


async def sweep(limit: int = 200) -> int:
    """Apply champion retention, drop stale uploads and delete files no live row owns."""
    now = datetime.now(UTC)
    grace = timedelta(minutes=get_settings().ml_model_orphan_grace_minutes)
    doomed: list[str] = []
    async with control_session_scope() as session:
        rows = (
            (
                await session.execute(
                    select(MlModelRelease)
                    .where(MlModelRelease.status.in_(("ready", "uploading")))
                    .with_for_update(skip_locked=True)
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            if (
                row.status == "ready"
                and retention_expired(row, now=now)
                or row.status == "uploading"
                and row.created_at < now - grace
            ):
                row.status = "deleted"
                row.deleted_at = now
                doomed.append(row.artifact_key)
        # Read without the skip-locked filter: a row locked by an admin action is still live.
        live = set(
            (
                await session.execute(
                    select(MlModelRelease.id).where(
                        MlModelRelease.status.in_(("ready", "uploading"))
                    )
                )
            )
            .scalars()
            .all()
        )
    await delete_keys(doomed)
    stored = await get_storage().list_keys(KEY_PREFIX)
    stale = orphan_keys(stored, live)[:limit]
    await delete_keys(stale)
    return len(doomed) + len(stale)
