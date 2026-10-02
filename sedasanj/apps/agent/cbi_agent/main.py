from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cbi_agent.ami import AmiClient
from cbi_agent.config import DEFAULT_PATH, AgentConfig, load_config
from cbi_agent.uploader import (
    PendingCall,
    Spool,
    Uploader,
    UploadResult,
    locate_recording,
    prepare_archive,
    rfc3339,
)

logger = logging.getLogger("cbi-agent")

RETRY_INTERVAL_SECONDS = 60
RECORDING_SETTLE_SECONDS = 2.0


def _agent_extension(event: dict[str, str]) -> str | None:
    for key in ("AgentExtension", "CBIAgentExtension"):
        value = (event.get(key) or "").strip()
        if value.isdigit():
            return value
    return None


def _pending_from_event(config: AgentConfig, event: dict[str, str], wav: Path) -> PendingCall:
    duration = int(event.get("Duration") or event.get("BillableSeconds") or 0)
    ended = datetime.now(UTC)
    started = ended - timedelta(seconds=duration)
    channel = event.get("Channel", "")
    return PendingCall(
        asterisk_uniqueid=event.get("Uniqueid", ""),
        wav_path=str(wav),
        caller_number=event.get("CallerIDNum", "") or "unknown",
        dialed_number=event.get("Exten") or event.get("ConnectedLineNum", "") or "unknown",
        started_at=rfc3339(started),
        ended_at=rfc3339(ended),
        direction="inbound" if channel.startswith("PJSIP/trunk") else None,
        agent_extension=_agent_extension(event),
    )


async def _handle_hangup(
    config: AgentConfig, spool: Spool, uploader: Uploader, event: dict[str, str]
) -> None:
    uniqueid = event.get("Uniqueid")
    if not uniqueid:
        return
    await asyncio.sleep(RECORDING_SETTLE_SECONDS)
    wav = locate_recording(config.asterisk.monitor_dir, uniqueid)
    if wav is None:
        logger.info("no recording for %s", uniqueid)
        return
    pending = _pending_from_event(config, event, wav)
    spool.add(pending)
    try:
        prepare_archive(pending, config)
        spool.update(pending)
        result = await uploader.upload(pending)
    except Exception:  # noqa: BLE001 - the on-disk spool retains the recording
        logger.exception("failed to prepare or upload %s", pending.asterisk_uniqueid)
        result = UploadResult.RETRYABLE
    if result == UploadResult.ACCEPTED:
        spool.remove(pending)
    elif result == UploadResult.PERMANENT:
        pending.last_error = "permanent rejection from ingest API"
        spool.dead_letter(pending)
    elif result == UploadResult.BLOCKED_CREDIT:
        pending.last_error = "blocked by insufficient credit"
        pending.next_attempt_epoch = (
            datetime.now(UTC).timestamp() + config.retry.credit_retry_seconds
        )
        spool.update(pending)
    else:
        spool.update(pending)


async def _retry_loop(spool: Spool, uploader: Uploader) -> None:
    while True:
        await asyncio.sleep(RETRY_INTERVAL_SECONDS)
        try:
            await uploader.drain(spool)
        except Exception:  # noqa: BLE001 - the loop must survive anything
            logger.exception("retry loop error")


async def run(config: AgentConfig) -> None:
    spool = Spool(config.spool_dir)
    uploader = Uploader(config)
    retry_task = asyncio.create_task(_retry_loop(spool, uploader))
    backoff = config.retry.backoff_seconds
    try:
        while True:
            ami = AmiClient(
                config.asterisk.ami_host,
                config.asterisk.ami_port,
                config.asterisk.ami_user,
                config.asterisk.ami_secret,
            )
            try:
                await ami.connect()
                logger.info("connected to AMI at %s", config.asterisk.ami_host)
                backoff = config.retry.backoff_seconds
                async for event in ami.events():
                    if event.get("Event") == "Hangup":
                        asyncio.create_task(_handle_hangup(config, spool, uploader, event))  # noqa: RUF006
            except (OSError, ConnectionError) as exc:
                logger.warning("AMI connection lost (%r); reconnecting in %ss", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 300)
            finally:
                await ami.close()
    finally:
        retry_task.cancel()
        await uploader.close()


def main() -> None:
    parser = argparse.ArgumentParser(prog="cbi-agent", description="CBI Asterisk upload agent")
    parser.add_argument("--config", type=Path, default=DEFAULT_PATH)
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument(
        "--drain-only", action="store_true", help="upload spooled recordings and exit"
    )
    args = parser.parse_args()
    logging.basicConfig(
        level=args.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    config = load_config(args.config)

    if args.drain_only:
        asyncio.run(_drain_once(config))
        return
    try:
        asyncio.run(run(config))
    except KeyboardInterrupt:
        logger.info("stopped")


async def _drain_once(config: AgentConfig) -> None:
    uploader = Uploader(config)
    try:
        await uploader.drain(Spool(config.spool_dir))
    finally:
        await uploader.close()


if __name__ == "__main__":
    main()
