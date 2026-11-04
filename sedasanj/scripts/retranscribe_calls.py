"""Queue recent calls for one tenant through the existing unbilled revision workflow."""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from sqlalchemy import Select, select  # noqa: E402

from app.db import dispose_engine, operational_tenant_ids, session_scope  # noqa: E402
from app.errors import ApiError  # noqa: E402
from app.models import (  # noqa: E402
    AsrTranscriptRevision,
    AudioObject,
    Call,
    Transcript,
    TranscriptRevision,
)
from app.services import audit, call_retranscription  # noqa: E402


def candidates(
    tenant_id: UUID, *, since: datetime, limit: int, campaign: str
) -> Select[tuple[UUID]]:
    excluded = (
        select(AsrTranscriptRevision.id)
        .where(
            AsrTranscriptRevision.tenant_id == tenant_id,
            AsrTranscriptRevision.call_id == Call.id,
            (AsrTranscriptRevision.status.in_(("queued", "running")))
            | (AsrTranscriptRevision.metrics["batch_campaign"].as_string() == campaign),
        )
        .exists()
    )
    correction_in_flight = (
        select(TranscriptRevision.id)
        .where(
            TranscriptRevision.tenant_id == tenant_id,
            TranscriptRevision.call_id == Call.id,
            TranscriptRevision.status.in_(("queued", "running", "validating")),
        )
        .exists()
    )
    return (
        select(Call.id)
        .join(Transcript, Transcript.call_id == Call.id)
        .join(AudioObject, AudioObject.id == Call.audio_id)
        .where(
            Call.tenant_id == tenant_id,
            Transcript.tenant_id == tenant_id,
            AudioObject.tenant_id == tenant_id,
            AudioObject.deleted_at.is_(None),
            Call.status.in_(call_retranscription.RETRANSCRIPTION_READY_STATUSES),
            Call.started_at >= since,
            ~excluded,
            ~correction_in_flight,
        )
        .order_by(Call.started_at.desc(), Call.id)
        .limit(limit)
    )


async def run(args: argparse.Namespace) -> None:
    if args.tenant not in await operational_tenant_ids():
        raise SystemExit("Select an active tenant.")
    since = datetime.now(UTC) - timedelta(days=args.days)
    async with session_scope(args.tenant) as session:
        call_ids = list(
            (
                await session.scalars(
                    candidates(args.tenant, since=since, limit=args.limit, campaign=args.campaign)
                )
            ).all()
        )
    if not args.apply:
        print(f"Dry run: {len(call_ids)} candidate call(s). Use --apply to queue revisions.")
        return

    queued = 0
    for call_id in call_ids:
        try:
            async with session_scope(args.tenant) as session:
                call = await session.get(Call, call_id, with_for_update=True)
                if call is None:
                    continue
                staged = await call_retranscription.stage(session, call, campaign=args.campaign)
                if staged is None:
                    continue
                revision_id, _ = staged
                await audit.record(
                    session,
                    actor_type="system",
                    actor_id=None,
                    tenant_id=args.tenant,
                    action="call.retranscribe_batch",
                    payload={
                        "call_id": str(call_id),
                        "asr_revision_id": str(revision_id),
                        "campaign": args.campaign,
                    },
                )
            queued += 1
        except ApiError as exc:
            if exc.code not in {"call_retranscription_busy", "invalid_request", "not_found"}:
                raise
        await asyncio.sleep(args.interval)
    print(f"Queued {queued} revision(s) through the durable outbox.")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", required=True, type=UUID)
    parser.add_argument("--campaign", required=True, help="Reuse this name to resume a batch.")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--interval", type=float, default=5.0, help="Seconds between queued calls.")
    parser.add_argument("--apply", action="store_true", help="Persist revisions and outbox jobs.")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", args.campaign):
        parser.error("--campaign must contain 1–64 letters, digits, underscores or hyphens")
    if not 1 <= args.days <= 365 or not 1 <= args.limit <= 500 or not 1 <= args.interval <= 3600:
        parser.error("Use --days 1–365, --limit 1–500 and --interval 1–3600")
    try:
        await run(args)
    finally:
        await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
