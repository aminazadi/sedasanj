from __future__ import annotations

import gzip
import time
import zipfile
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from cbi_agent.config import ArchiveConfig
from cbi_agent.main import _agent_extension
from cbi_agent.uploader import (
    PendingCall,
    Spool,
    Uploader,
    UploadResult,
    locate_recording,
    prepare_archive,
    rfc3339,
)


def test_hangup_extension_is_not_assumed_to_be_the_answering_operator() -> None:
    assert _agent_extension({"Exten": "201"}) is None
    assert _agent_extension({"AgentExtension": "202", "Exten": "s"}) == "202"
    assert _agent_extension({"CBIAgentExtension": " 203 "}) == "203"
    assert _agent_extension({"AgentExtension": "PJSIP/204-0001"}) is None


def _pending(tmp_path: Path, uniqueid: str = "1750000000.42") -> PendingCall:
    wav = tmp_path / f"{uniqueid}.wav"
    wav.write_bytes(b"RIFF")
    return PendingCall(
        asterisk_uniqueid=uniqueid,
        wav_path=str(wav),
        caller_number="09120000000",
        dialed_number="1000",
        started_at=rfc3339(datetime(2026, 3, 1, 9, 0, tzinfo=UTC)),
        ended_at=rfc3339(datetime(2026, 3, 1, 9, 2, tzinfo=UTC)),
        direction="inbound",
        agent_extension="201",
    )


def test_pending_call_survives_a_disk_roundtrip(tmp_path: Path) -> None:
    pending = _pending(tmp_path)
    assert PendingCall.from_json(pending.to_json()) == pending


def test_spool_persists_across_restarts(tmp_path: Path) -> None:
    spool_dir = tmp_path / "spool"
    pending = _pending(tmp_path)
    Spool(spool_dir).add(pending)

    # A fresh Spool models the agent restarting after platform downtime (§11.4).
    reloaded = Spool(spool_dir).all()
    assert [item.asterisk_uniqueid for item in reloaded] == [pending.asterisk_uniqueid]


def test_spool_update_tracks_attempts_and_remove_clears(tmp_path: Path) -> None:
    spool = Spool(tmp_path / "spool")
    pending = _pending(tmp_path)
    spool.add(pending)
    spool.update(replace(pending, attempts=3))
    assert spool.all()[0].attempts == 3
    spool.remove(pending)
    assert spool.all() == []


def test_dead_letter_keeps_audio_archive_and_updated_metadata(tmp_path: Path) -> None:
    spool = Spool(tmp_path / "spool")
    pending = _pending(tmp_path)
    archive = tmp_path / "call.wav.gz"
    archive.write_bytes(b"archive")
    pending.archive_path = str(archive)
    pending.archive_format = "gzip"
    spool.add(pending)

    metadata = spool.dead_letter(pending)
    recovered = PendingCall.from_json(metadata.read_text(encoding="utf-8"))

    assert Path(recovered.wav_path).read_bytes() == b"RIFF"
    assert recovered.archive_path is not None
    assert Path(recovered.archive_path).read_bytes() == b"archive"
    assert spool.all() == []


def test_locate_recording_prefers_separate_legs_over_mixed_file(tmp_path: Path) -> None:
    uniqueid = "1750000000.7"
    (tmp_path / f"{uniqueid}.wav").write_bytes(b"RIFF-mixed")
    (tmp_path / f"{uniqueid}-in.wav").write_bytes(b"RIFF-in")
    (tmp_path / f"{uniqueid}-out.wav").write_bytes(b"RIFF-out")

    def fake_merge(in_leg: Path, out_leg: Path, target: Path) -> None:
        assert in_leg.name == f"{uniqueid}-in.wav"
        assert out_leg.name == f"{uniqueid}-out.wav"
        target.write_bytes(b"RIFF-stereo")

    with patch("cbi_agent.uploader.merge_legs", fake_merge):
        found = locate_recording(tmp_path, uniqueid)

    assert found is not None and found.name == f"{uniqueid}-stereo.wav"


def test_locate_recording_falls_back_to_mixed_file_without_both_legs(tmp_path: Path) -> None:
    uniqueid = "1750000000.8"
    (tmp_path / f"{uniqueid}.wav").write_bytes(b"RIFF-mixed")
    (tmp_path / f"{uniqueid}-in.wav").write_bytes(b"RIFF-in")

    found = locate_recording(tmp_path, uniqueid)

    assert found is not None and found.name == f"{uniqueid}.wav"


def test_locate_recording_returns_none_without_legs(tmp_path: Path) -> None:
    assert locate_recording(tmp_path, "missing") is None


def test_prepare_archive_creates_reusable_gzip(tmp_path: Path) -> None:
    pending = _pending(tmp_path)
    config = type("Config", (), {"archive": ArchiveConfig(format="gzip")})()
    first, archive_format = prepare_archive(pending, config)  # type: ignore[arg-type]
    second, _ = prepare_archive(pending, config)  # type: ignore[arg-type]
    assert archive_format == "gzip"
    assert first == second
    assert gzip.decompress(first.read_bytes()) == Path(pending.wav_path).read_bytes()


def test_prepare_archive_creates_unencrypted_zip(tmp_path: Path) -> None:
    pending = _pending(tmp_path)
    config = type("Config", (), {"archive": ArchiveConfig(format="zip")})()
    archive_path, archive_format = prepare_archive(pending, config)  # type: ignore[arg-type]
    assert archive_format == "zip"
    with zipfile.ZipFile(archive_path) as archive:
        assert archive.namelist() == [Path(pending.wav_path).name]
        assert archive.read(archive.namelist()[0]) == b"RIFF"


async def test_credit_block_does_not_consume_attempt(tmp_path: Path) -> None:
    spool = Spool(tmp_path / "spool")
    pending = _pending(tmp_path)
    pending.attempts = 4
    spool.add(pending)
    config = type(
        "Config",
        (),
        {
            "archive": ArchiveConfig(format="wav"),
            "retry": type(
                "Retry",
                (),
                {
                    "backoff_seconds": 30,
                    "retry_max_seconds": 3600,
                    "credit_retry_seconds": 3600,
                    "max_attempts": 8,
                },
            )(),
        },
    )()
    uploader = Uploader.__new__(Uploader)
    uploader._config = config  # type: ignore[assignment]

    async def blocked(_pending: PendingCall) -> UploadResult:
        return UploadResult.BLOCKED_CREDIT

    uploader.upload = blocked  # type: ignore[method-assign]
    before = time.time()
    await uploader.drain(spool)
    reloaded = spool.all()[0]
    assert reloaded.attempts == 4
    assert reloaded.next_attempt_epoch >= before + 3599
