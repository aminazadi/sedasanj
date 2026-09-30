from __future__ import annotations

import gzip
import hashlib
import json
import logging
import re
import secrets
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

import httpx
import pyzipper

from cbi_agent.config import AgentConfig

logger = logging.getLogger(__name__)


def _safe_response_text(value: str) -> str:
    return re.sub(r"sk_live_[A-Za-z0-9_-]+", "[REDACTED]", value[:300])


@dataclass
class PendingCall:
    """A recording waiting for the platform. Persisted so downtime never loses calls."""

    asterisk_uniqueid: str
    wav_path: str
    caller_number: str
    dialed_number: str
    started_at: str
    ended_at: str
    direction: str | None = None
    agent_extension: str | None = None
    attempts: int = 0
    archive_path: str | None = None
    archive_format: str | None = None
    next_attempt_epoch: float = 0
    last_error: str | None = None
    created_at: str = ""

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str) -> PendingCall:
        return cls(**json.loads(raw))


def merge_legs(in_leg: Path, out_leg: Path, target: Path) -> None:
    """Merge the r()/t() mono legs into stereo: left = caller, right = callee (§4.1)."""
    subprocess.run(  # noqa: S603 - fixed argv, no shell
        [
            "ffmpeg",
            "-y",
            "-i",
            str(in_leg),
            "-i",
            str(out_leg),
            "-filter_complex",
            "[0:a][1:a]amerge=inputs=2[a]",
            "-map",
            "[a]",
            "-acodec",
            "pcm_s16le",
            str(target),
        ],
        check=True,
        capture_output=True,
    )


def locate_recording(monitor_dir: Path, uniqueid: str) -> Path | None:
    """Prefer the separate r()/t() legs; the main MixMonitor file is mixed mono."""
    in_leg = monitor_dir / f"{uniqueid}-in.wav"
    out_leg = monitor_dir / f"{uniqueid}-out.wav"
    if in_leg.exists() and out_leg.exists():
        merged = monitor_dir / f"{uniqueid}-stereo.wav"
        merge_legs(in_leg, out_leg, merged)
        return merged
    mixed = monitor_dir / f"{uniqueid}.wav"
    if mixed.exists():
        return mixed
    return None


class UploadResult(StrEnum):
    ACCEPTED = "accepted"
    RETRYABLE = "retryable"
    BLOCKED_CREDIT = "blocked_credit"
    PERMANENT = "permanent"


def prepare_archive(pending: PendingCall, config: AgentConfig) -> tuple[Path, str]:
    wav = Path(pending.wav_path)
    archive_format = pending.archive_format or config.archive.format
    if pending.archive_path:
        existing = Path(pending.archive_path)
        if existing.exists():
            return existing, archive_format
    if archive_format == "wav":
        pending.archive_path = str(wav)
        pending.archive_format = "wav"
        return wav, "wav"
    if archive_format == "gzip":
        target = wav.with_suffix(wav.suffix + ".gz")
        with (
            wav.open("rb") as source,
            target.open("wb") as raw_output,
            gzip.GzipFile(filename=wav.name, mode="wb", fileobj=raw_output) as output,
        ):
            shutil.copyfileobj(source, output)
    elif archive_format == "zip":
        target = wav.with_suffix(".zip")
        options = {"encryption": pyzipper.WZ_AES} if config.archive.password else {}
        with pyzipper.AESZipFile(
            target, "w", compression=pyzipper.ZIP_DEFLATED, **options
        ) as archive:
            if config.archive.password:
                archive.setpassword(config.archive.password.encode("utf-8"))
                archive.setencryption(pyzipper.WZ_AES, nbits=256)
            archive.write(wav, arcname=wav.name)
    else:
        raise ValueError(f"unsupported archive format: {archive_format}")
    pending.archive_path = str(target)
    pending.archive_format = archive_format
    return target, archive_format


class Spool:
    """On-disk retry queue (§4). Files stay until the platform accepts them."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, uniqueid: str) -> Path:
        stable_id = hashlib.sha256(uniqueid.encode("utf-8")).hexdigest()[:40]
        return self.directory / f"{stable_id}.json"

    def add(self, pending: PendingCall) -> None:
        if not pending.created_at:
            pending.created_at = rfc3339()
        target = self._path(pending.asterisk_uniqueid)
        temporary = target.with_name(f".{target.name}.{secrets.token_hex(8)}.tmp")
        temporary.write_text(pending.to_json(), encoding="utf-8")
        temporary.replace(target)

    def update(self, pending: PendingCall) -> None:
        self.add(pending)

    def remove(self, pending: PendingCall) -> None:
        self._path(pending.asterisk_uniqueid).unlink(missing_ok=True)
        legacy = self.directory / f"{pending.asterisk_uniqueid}.json"
        if legacy.parent == self.directory:
            legacy.unlink(missing_ok=True)

    def dead_letter(self, pending: PendingCall) -> Path:
        """Keep exhausted entries for manual replay instead of losing the call."""
        safe_id = hashlib.sha256(pending.asterisk_uniqueid.encode("utf-8")).hexdigest()[:20]
        failed = self.directory / "failed" / safe_id
        failed.mkdir(parents=True, exist_ok=True)
        original_paths = {
            Path(value)
            for value in (pending.wav_path, pending.archive_path)
            if value is not None
        }
        relocated: dict[Path, Path] = {}
        for source in original_paths:
            if not source.exists():
                continue
            destination = failed / source.name
            if source.resolve() != destination.resolve():
                shutil.move(str(source), destination)
            relocated[source] = destination
        wav_path = Path(pending.wav_path)
        if wav_path in relocated:
            pending.wav_path = str(relocated[wav_path])
        if pending.archive_path is not None:
            archive_path = Path(pending.archive_path)
            if archive_path in relocated:
                pending.archive_path = str(relocated[archive_path])
        target = failed / "metadata.json"
        temporary = failed / f".metadata.{secrets.token_hex(8)}.tmp"
        temporary.write_text(pending.to_json(), encoding="utf-8")
        temporary.replace(target)
        self.remove(pending)
        return target

    def all(self) -> list[PendingCall]:
        items: list[PendingCall] = []
        for path in sorted(self.directory.glob("*.json")):
            try:
                pending = PendingCall.from_json(path.read_text(encoding="utf-8"))
                target = self._path(pending.asterisk_uniqueid)
                if path != target:
                    if target.exists():
                        path.unlink()
                        continue
                    path.replace(target)
                items.append(pending)
            except (OSError, ValueError, TypeError):
                logger.warning("retaining unreadable spool entry for manual recovery: %s", path)
        return items


class Uploader:
    def __init__(self, config: AgentConfig) -> None:
        self._config = config
        self._client = httpx.AsyncClient(
            base_url=config.server.base_url,
            timeout=config.server.timeout_seconds,
            headers={"Authorization": f"Bearer {config.api_key}"},
        )

    async def health(self) -> bool:
        try:
            response = await self._client.get("/v1/ingest/health")
        except httpx.HTTPError:
            return False
        return response.is_success

    async def upload(self, pending: PendingCall) -> UploadResult:
        wav = Path(pending.wav_path)
        if not wav.exists():
            logger.error("recording vanished: %s", wav)
            return UploadResult.PERMANENT
        upload_path, archive_format = prepare_archive(pending, self._config)
        data = {
            "asterisk_uniqueid": pending.asterisk_uniqueid,
            "caller_number": pending.caller_number,
            "dialed_number": pending.dialed_number,
            "started_at": pending.started_at,
            "ended_at": pending.ended_at,
        }
        if pending.direction:
            data["direction"] = pending.direction
        if pending.agent_extension:
            data["agent_extension"] = pending.agent_extension

        try:
            content_type = {
                "wav": "audio/wav",
                "gzip": "application/gzip",
                "zip": "application/zip",
            }[archive_format]
            headers = {"Idempotency-Key": pending.asterisk_uniqueid}
            if archive_format == "zip" and self._config.archive.password:
                headers["X-CBI-Archive-Password"] = self._config.archive.password
            with upload_path.open("rb") as handle:
                response = await self._client.post(
                    "/v1/ingest/calls",
                    data=data,
                    files={"file": (upload_path.name, handle, content_type)},
                    headers=headers,
                )
        except httpx.HTTPError as exc:
            logger.warning("upload failed for %s: %r", pending.asterisk_uniqueid, exc)
            return UploadResult.RETRYABLE

        if response.is_success:
            logger.info(
                "uploaded %s -> %s", pending.asterisk_uniqueid, response.json().get("call_id")
            )
            if self._config.audio.delete_after_upload:
                wav.unlink(missing_ok=True)
                if upload_path != wav:
                    upload_path.unlink(missing_ok=True)
            else:
                archive = wav.parent / "uploaded"
                archive.mkdir(exist_ok=True)
                shutil.move(str(wav), archive / wav.name)
                if upload_path != wav:
                    shutil.move(str(upload_path), archive / upload_path.name)
            return UploadResult.ACCEPTED

        if response.status_code == 402:
            logger.warning("upload blocked by credit for %s", pending.asterisk_uniqueid)
            return UploadResult.BLOCKED_CREDIT

        if response.status_code in (400, 401, 403, 409, 413, 415, 422):
            logger.error(
                "permanent rejection %s for %s: %s",
                response.status_code,
                pending.asterisk_uniqueid,
                _safe_response_text(response.text),
            )
            return UploadResult.PERMANENT

        logger.warning("retryable %s for %s", response.status_code, pending.asterisk_uniqueid)
        return UploadResult.RETRYABLE

    async def drain(self, spool: Spool) -> None:
        for pending in spool.all():
            if pending.next_attempt_epoch > time.time():
                continue
            try:
                prepare_archive(pending, self._config)
                spool.update(pending)
                result = await self.upload(pending)
            except Exception:  # noqa: BLE001 - one broken entry must not block the queue
                logger.exception("failed to prepare or upload %s", pending.asterisk_uniqueid)
                result = UploadResult.RETRYABLE
            if result == UploadResult.ACCEPTED:
                spool.remove(pending)
                continue
            if result == UploadResult.PERMANENT:
                pending.last_error = "permanent rejection from ingest API"
                target = spool.dead_letter(pending)
                logger.error(
                    "permanent rejection for %s; entry kept at %s",
                    pending.asterisk_uniqueid,
                    target,
                )
                continue
            if result == UploadResult.BLOCKED_CREDIT:
                pending.last_error = "blocked by insufficient credit"
                pending.next_attempt_epoch = time.time() + self._config.retry.credit_retry_seconds
                spool.update(pending)
                continue
            pending.attempts += 1
            pending.last_error = "retryable upload failure"
            pending.next_attempt_epoch = 0
            if pending.attempts >= self._config.retry.max_attempts:
                target = spool.dead_letter(pending)
                logger.error(
                    "giving up on %s after %s attempts; entry kept at %s",
                    pending.asterisk_uniqueid,
                    pending.attempts,
                    target,
                )
            else:
                delay = min(
                    self._config.retry.backoff_seconds * 2 ** max(0, pending.attempts - 1),
                    self._config.retry.retry_max_seconds,
                )
                pending.next_attempt_epoch = time.time() + delay
                spool.update(pending)

    async def close(self) -> None:
        await self._client.aclose()


def rfc3339(moment: datetime | None = None) -> str:
    return (moment or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ")
