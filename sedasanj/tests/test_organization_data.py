from __future__ import annotations

import base64
import gzip
import hashlib
import io
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4
from zipfile import ZipFile

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text

from app import db
from app.config import get_settings
from app.errors import ApiError, install_error_handlers
from app.models import Base, OrganizationBackupSettings, OrganizationDataRun
from app.routers import organization_data
from app.security import create_access_token
from app.services import ratelimit
from app.services.organization_data import archive, dataset, ftp, jobs
from app.services.storage import get_storage, set_storage


def test_authenticated_binary_archive(tmp_path: Path) -> None:
    source, encrypted, restored = (tmp_path / name for name in ("src", "enc", "out"))
    payload = bytes(range(256)) * 5000
    source.write_bytes(payload)
    key = bytes(range(32))
    assert archive.recovery_key(base64.urlsafe_b64encode(key).decode().rstrip("=")) == key
    size, checksum = archive.seal(source, encrypted, key, 2_000_000)
    raw = encrypted.read_bytes()
    assert raw.startswith(archive.MAGIC)
    assert size == len(raw) and checksum == hashlib.sha256(raw).hexdigest()
    archive.unseal(encrypted, restored, key, 2_000_000)
    assert restored.read_bytes() == payload
    with pytest.raises(ApiError, match="کلید بازیابی") as error:
        archive.unseal(encrypted, restored, bytes(32), 2_000_000)
    assert error.value.code == "org_archive_invalid"
    assert not restored.exists()
    encrypted.write_bytes(raw[:-20] + bytes(20))
    with pytest.raises(ApiError) as error:
        archive.unseal(encrypted, restored, key, 2_000_000)
    assert error.value.code == "org_archive_invalid"
    assert not restored.exists()
    with pytest.raises(ApiError) as error:
        archive.unseal(encrypted, restored, key, 100)
    assert error.value.code == "org_archive_too_large"


def test_gzip_archive_is_lossless_and_authenticates_before_extraction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = bytes(range(32))
    payload = tmp_path / "data.zip.gzip"
    published = tmp_path / "export.gzip"
    output = tmp_path / "restored.zip"
    audio = bytes(range(256)) * 10_000
    member = f"media/audio_objects/{uuid4().hex}"
    with archive.write_zip(payload, gzip_payload=True) as writer:
        writer.writestr(member, audio)
    assert payload.stat().st_size < len(audio) // 20

    limit = 100_000
    size, checksum = archive.seal_gzip(payload, published, key, limit)
    saved = published.read_bytes()
    assert size == len(saved) and checksum == hashlib.sha256(saved).hexdigest()
    assert archive.is_supported(published)
    envelope = gzip.decompress(saved)
    assert envelope.startswith(archive.GZIP_ENVELOPE)
    archive.unseal_gzip(published, output, key, limit, len(audio))
    with archive.open_zip(output) as reader:
        assert reader.read(member) == audio

    for damaged, wrong_key in (
        (saved, bytes(32)),
        (saved[:-1], key),
        (gzip.compress(envelope[:-1] + bytes([envelope[-1] ^ 1])), key),
        (gzip.compress(b"not a SedaSanj backup"), key),
    ):
        published.write_bytes(damaged)
        with pytest.raises(ApiError) as invalid:
            archive.unseal_gzip(published, output, wrong_key, limit, len(audio))
        assert invalid.value.code == "org_archive_invalid"
        assert not output.exists()
    published.write_bytes(saved)
    with pytest.raises(ApiError) as oversized:
        archive.unseal_gzip(published, output, key, len(saved) - 1, len(audio))
    assert oversized.value.code == "org_archive_too_large"
    monkeypatch.setattr(archive, "MAX_ZIP_DIRECTORY_BYTES", 1024)
    monkeypatch.setattr(archive, "MAX_ROWS", 1)
    with pytest.raises(ApiError) as oversized:
        archive.unseal_gzip(published, output, key, limit, 1024)
    assert oversized.value.code == "org_archive_too_large"
    assert not output.exists()


def test_ftp_verifies_uploaded_hash_before_publish(tmp_path: Path) -> None:
    path = tmp_path / "export.gzip"
    path.write_bytes(b"expected")

    class Remote:
        def __init__(self) -> None:
            self.files: dict[str, bytes] = {}
            self.corrupt = True

        def voidcmd(self, _command) -> None:
            pass

        def size(self, name):
            return len(self.files[name]) if name in self.files else None

        def storbinary(self, command, source, _size, callback) -> None:
            payload = source.read()
            callback(payload)
            self.files[command[5:]] = b"damaged!" if self.corrupt else payload

        def retrbinary(self, command, callback) -> None:
            callback(self.files[command[5:]])

        def rename(self, source, target) -> None:
            self.files[target] = self.files.pop(source)

        def delete(self, name) -> None:
            del self.files[name]

    remote = Remote()
    with pytest.raises(OSError, match="integrity"):
        ftp._publish(remote, path, path.name, 10)
    assert not remote.files
    remote.corrupt = False
    ftp._publish(remote, path, path.name, 10)
    assert remote.files == {path.name: b"expected"}
    remote.corrupt = True
    ftp._publish(remote, path, path.name, 10)
    assert remote.files == {path.name: b"expected"}


@pytest.mark.parametrize("name", ("../payload", "/etc/test", "rows/not-allowed.ndjson"))
def test_archive_rejects_unexpected_paths(name: str) -> None:
    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as data:
        data.writestr(
            "manifest.json",
            archive.json_bytes(
                {
                    "version": 1,
                    "media": {},
                    "owners": {},
                    "counts": {},
                }
            ),
        )
        data.writestr(name, "sample")
    with ZipFile(buffer) as data, pytest.raises(ApiError) as error:
        dataset._entries(data, 1024)
    assert error.value.code == "org_archive_invalid"


def test_next_occurrence_skips_gap_and_runs_once_at_fold() -> None:
    assert jobs.next_occurrence(
        datetime(2026, 11, 4, 0, tzinfo=UTC),
        "Asia/Tehran",
        "weekly",
        "02:00",
        5,
    ) == datetime(2026, 11, 6, 22, 30, tzinfo=UTC)
    assert jobs.next_occurrence(
        datetime(2026, 3, 8, 3, tzinfo=UTC),
        "America/New_York",
        "daily",
        "02:30",
        0,
    ) == datetime(2026, 3, 9, 6, 30, tzinfo=UTC)
    assert jobs.next_occurrence(
        datetime(2026, 11, 1, 6, tzinfo=UTC),
        "America/New_York",
        "daily",
        "01:30",
        0,
    ) == datetime(2026, 11, 2, 6, 30, tzinfo=UTC)


def test_ftp_rejects_private_dns_and_pins_data_to_control_peer(monkeypatch) -> None:
    import socket
    from types import SimpleNamespace

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("8.8.8.8", 21)),
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("127.0.0.1", 21)),
        ],
    )
    with pytest.raises(ApiError) as error:
        ftp.public_address("public.example", 21)
    assert error.value.code == "org_backup_destination"
    client = SimpleNamespace(
        af=socket.AF_INET,
        sock=SimpleNamespace(getpeername=lambda: ("8.8.8.8", 21)),
        sendcmd=lambda _: "227 Entering Passive Mode (127,0,0,1,195,80)",
    )
    assert ftp._passive_peer(client) == ("8.8.8.8", 50000)


async def _insert(session, table: str, **values: Any) -> None:
    await session.execute(Base.metadata.tables[table].insert().values(**values))


async def _seed(source: UUID, target: UUID, wav: bytes):
    owner, admin, operator, target_operator, audio, call, meeting, team, report, chat = (
        uuid4() for _ in range(10)
    )
    now = datetime.now(UTC)
    profile, attendee = uuid4(), uuid4()
    storage = get_storage()
    object_key = f"{source}/qa.wav"
    await storage.ensure_bucket()
    await storage.put(object_key, wav)
    async with db.control_session_scope() as session:
        for org in (source, target):
            await _insert(session, "tenants", id=org, name="Archive QA", price_per_minute_toman=1)
        for uid, tenant, role in (
            (owner, source, "org_admin"),
            (operator, source, "operator"),
            (admin, target, "org_admin"),
            (target_operator, target, "operator"),
        ):
            await _insert(
                session,
                "users",
                id=uid,
                tenant_id=tenant,
                role=role,
                email=f"{uid}@example.test",
                password_hash="test-fixture",
            )
        await _insert(
            session,
            "audio_objects",
            id=audio,
            tenant_id=source,
            bucket=storage.bucket,
            object_key=object_key,
            sha256=hashlib.sha256(wav).hexdigest(),
            bytes=len(wav),
            sample_rate=8000,
            channels=1,
            duration_ms=1000,
        )
        await _insert(
            session,
            "calls",
            id=call,
            tenant_id=source,
            audio_id=audio,
            asterisk_uniqueid=str(call),
            started_at=now,
            ended_at=now,
            duration_ms=1000,
            status="complete",
        )
        await _insert(
            session,
            "calls",
            tenant_id=source,
            asterisk_uniqueid=str(uuid4()),
            started_at=now,
            ended_at=now,
            duration_ms=1000,
            status="received",
        )
        await _insert(
            session,
            "transcripts",
            tenant_id=source,
            call_id=call,
            full_text="test",
            asr_model="fixture",
            asr_version="1",
        )
        await _insert(session, "call_insights", tenant_id=source, call_id=call, summary="test")
        await _insert(
            session,
            "call_knowledge",
            tenant_id=source,
            call_id=call,
            summary="test",
            graph_status="pending",
            vector_status="pending",
        )
        await _insert(
            session, "contacts", tenant_id=source, phone_number="021000001", name="Source"
        )
        await _insert(
            session, "contacts", tenant_id=target, phone_number="021000001", name="Target"
        )
        await _insert(session, "teams", id=team, tenant_id=source, name="QA")
        await _insert(
            session,
            "team_memberships",
            tenant_id=source,
            team_id=team,
            operator_id=operator,
            valid_from=now,
        )
        await _insert(
            session,
            "kpi_goals",
            tenant_id=source,
            team_id=team,
            metric="calls",
            target_value=4,
            valid_from=now,
            valid_to=now + timedelta(days=1),
        )
        await _insert(
            session,
            "follow_up_tasks",
            tenant_id=source,
            call_id=call,
            title="Test task",
            assignee_id=owner,
        )
        await _insert(
            session,
            "meetings",
            id=meeting,
            tenant_id=source,
            owner_user_id=owner,
            audio_id=audio,
            client_meeting_id=uuid4(),
            started_at=now,
            status="complete",
        )
        await _insert(
            session,
            "meeting_minutes",
            tenant_id=source,
            meeting_id=meeting,
            version=1,
            content_md="# Test",
            is_selected=True,
        )
        await _insert(
            session,
            "speaker_profiles",
            id=profile,
            tenant_id=source,
            owner_user_id=owner,
            client_id=attendee,
            display_name="Private profile",
            change_seq=1,
        )
        await _insert(
            session,
            "meeting_speakers",
            tenant_id=source,
            meeting_id=meeting,
            speaker_idx=0,
            label="Speaker label",
            profile_id=profile,
        )
        await _insert(
            session,
            "meeting_attendees",
            tenant_id=source,
            meeting_id=meeting,
            profile_client_id=attendee,
            profile_id=profile,
            name="Attendance label",
        )
        await _insert(
            session,
            "chat_conversations",
            id=chat,
            tenant_id=source,
            owner_id=owner,
            call_id=call,
        )
        await _insert(
            session,
            "chat_messages",
            conversation_id=chat,
            tenant_id=source,
            role="assistant",
            content="Test source",
            sources=[{"call_id": str(call)}],
        )
        await _insert(
            session,
            "organization_memories",
            tenant_id=source,
            logical_key="test",
            version=1,
            category="freeform",
            applies_to=["assistant"],
            title="Test",
            content="Test",
            status="active",
        )
        await _insert(
            session,
            "tenant_ai_instructions",
            tenant_id=source,
            scope="coach",
            instructions="Test",
            updated_by_type="user",
            updated_by=owner,
        )
        await _insert(
            session,
            "scheduled_reports",
            id=report,
            tenant_id=source,
            name="Test",
            instructions="Test",
            schedule_mode="fixed",
            fixed_hours=[2],
            window_start=now,
            enabled=True,
            next_run_at=now,
        )
        await _insert(
            session,
            "scheduled_report_runs",
            tenant_id=source,
            report_id=report,
            trigger="manual",
            idempotency_key=str(uuid4()),
            name="Test",
            instructions="Test",
            from_date=now,
            to_date=now + timedelta(hours=1),
            timezone="Asia/Tehran",
            status="succeeded",
        )
    return owner, admin, operator, target_operator


@pytest.mark.skipif(not os.getenv("ORG_DATA_TEST_DSN"), reason="disposable PostgreSQL DSN required")
@pytest.mark.parametrize("gzip_payload", [False, True])
async def test_portable_archive_api_and_worker(monkeypatch, wav_factory, gzip_payload) -> None:
    monkeypatch.setenv("DATABASE_URL", os.environ["ORG_DATA_TEST_DSN"])
    monkeypatch.setenv("TENANT_DATABASES_ENABLED", "false")
    monkeypatch.setenv("ORG_ARCHIVE_WRITE_V2", "true" if gzip_payload else "false")
    monkeypatch.setenv("PLATFORM_SECRETS_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("MINIO_BUCKET_AUDIO", f"org-data-qa-{uuid4().hex}")
    monkeypatch.setenv("STORAGE_BACKEND", "s3" if os.getenv("MINIO_ENDPOINT") else "memory")
    get_settings.cache_clear()
    set_storage(None)

    async def allow(*args, **kwargs):
        return None

    monkeypatch.setattr(ratelimit, "enforce", allow)
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(organization_data.router)
    source, target = uuid4(), uuid4()
    audio = wav_factory()
    owner, admin, operator, target_operator = await _seed(source, target, audio)

    def auth(user: UUID, tenant: UUID, role: str = "org_admin") -> dict[str, str]:
        token = create_access_token(subject=user, tenant_id=tenant, role=role)
        return {"Authorization": f"Bearer {token}"}

    key = base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip("=")
    route = "/v1/account/data"
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            src, dst = auth(owner, source), auth(admin, target)
            response = await client.put(
                f"{route}/backup/recovery-key", json={"key": key}, headers=src
            )
            assert response.status_code == 200 and key not in response.text
            assert (
                await client.get(
                    f"{route}/backup/settings",
                    headers=auth(operator, source, "operator"),
                )
            ).status_code == 403
            response = await client.post(f"{route}/backup", headers=src)
            assert response.status_code == 202, response.text
            backup = response.json()["id"]
            assert await jobs.run_one()
            summary = (await client.get(f"{route}/runs/{backup}", headers=src)).json()
            assert summary["state"] == "succeeded", summary
            assert summary["summary"]["omitted"]["calls"] == 1
            assert (await client.get(f"{route}/runs/{backup}", headers=dst)).status_code == 404
            download = f"{route}/runs/{backup}/download"
            assert (await client.get(download)).status_code == 404
            assert (await client.post(download, headers=src)).status_code == 204
            response = await client.get(download)
            assert response.status_code == 200
            content = response.content
            expected_type = "application/gzip" if gzip_payload else "application/octet-stream"
            suffix = ".gzip" if gzip_payload else ".sedasanj"
            assert response.headers["content-type"] == expected_type
            assert response.headers["content-disposition"].endswith(f'{suffix}"')
            assert "content-encoding" not in response.headers
            assert summary["checksum"] == hashlib.sha256(content).hexdigest()
            if gzip_payload:
                assert gzip.decompress(content).startswith(archive.GZIP_ENVELOPE)
            else:
                assert content.startswith(archive.MAGIC)

            async def upload(recovery_key: str = key) -> tuple[str, dict[str, Any]]:
                created = await client.post(
                    f"{route}/import",
                    headers=dst,
                    json={"key": recovery_key},
                )
                assert created.status_code == 201, created.text
                run_id = created.json()["id"]
                response = await client.put(
                    f"{route}/import/{run_id}/file",
                    content=content,
                    headers={**dst, "Content-Type": expected_type},
                )
                assert response.status_code == 202, response.text
                assert response.json()["checksum"] == summary["checksum"]
                assert await jobs.run_one()
                review = (await client.get(f"{route}/runs/{run_id}", headers=dst)).json()
                return run_id, review

            _, invalid = await upload(base64.urlsafe_b64encode(bytes(32)).decode().rstrip("="))
            assert invalid["state"] == "failed"
            assert invalid["error_code"] == "org_archive_invalid"

            failed_run, failed_review = await upload()
            assert failed_review["state"] == "review"
            response = await client.post(f"{route}/import/{failed_run}/confirm", headers=dst)
            assert response.status_code == 202, response.text
            storage = get_storage()
            real_put = storage.put_path

            async def fail_after_put(object_key, path, **kwargs):
                await real_put(object_key, path, **kwargs)
                if "/restored/" in object_key:
                    raise OSError("simulated interrupted media write")

            with monkeypatch.context() as failing_storage:
                failing_storage.setattr(storage, "put_path", fail_after_put)
                assert await jobs.run_one()
            failed = (await client.get(f"{route}/runs/{failed_run}", headers=dst)).json()
            assert failed["error_code"] == "org_archive_unavailable"
            assert not await storage.list_keys(f"{target}/restored/{failed_run}/")
            async with db.session_scope(target) as session:
                assert (
                    await session.scalar(
                        text("SELECT count(*) FROM calls WHERE tenant_id = :tenant"),
                        {"tenant": target},
                    )
                    == 0
                )

            run_id, review = await upload()
            assert review["state"] == "review", review
            counts = review["summary"]["counts"]
            assert counts["contacts"]["duplicate"] == counts["team_memberships"]["skipped"] == 1
            assert counts["calls"]["new"] == counts["meeting_minutes"]["new"] == 1
            assert any(
                row["id"] == str(owner) and row["target"] == str(admin) and row["fallback"] > 0
                for row in review["summary"]["owners"]
            )
            response = await client.put(
                f"{route}/import/{run_id}/mapping",
                headers=dst,
                json={"mappings": {str(operator): str(target_operator)}},
            )
            assert response.status_code == 202, response.text
            assert await jobs.run_one()
            response = await client.post(f"{route}/import/{run_id}/confirm", headers=dst)
            assert response.status_code == 202, response.text
            assert await jobs.run_one()
            result = (await client.get(f"{route}/runs/{run_id}", headers=dst)).json()
            assert result["state"] == "succeeded", result
            assert result["summary"]["counts"]["team_memberships"]["new"] == 1

            async with db.session_scope(target) as session:
                object_key = await session.scalar(
                    text(
                        "SELECT a.object_key FROM audio_objects a JOIN calls c ON c.audio_id=a.id "
                        "WHERE c.tenant_id=:id",
                    ),
                    {"id": target},
                )
                assert await get_storage().get(object_key) == audio
                speaker = (
                    await session.execute(
                        text("SELECT label, profile_id FROM meeting_speakers WHERE tenant_id=:id"),
                        {"id": target},
                    )
                ).one()
                assert tuple(speaker) == ("Speaker label", None)
                attendees = (
                    await session.execute(
                        text("SELECT name, profile_id FROM meeting_attendees WHERE tenant_id=:id"),
                        {"id": target},
                    )
                ).all()
                assert list(map(tuple, attendees)) == (
                    [("Attendance label", None)] if gzip_payload else []
                )
                assert (
                    await session.scalar(
                        text(
                            "SELECT owner_user_id FROM meetings WHERE tenant_id=:id",
                        ),
                        {"id": target},
                    )
                    == admin
                )
                assert not await session.scalar(
                    text(
                        "SELECT enabled FROM scheduled_reports WHERE tenant_id=:id",
                    ),
                    {"id": target},
                )
                assert (
                    await session.scalar(
                        text(
                            "SELECT name FROM contacts WHERE tenant_id=:id",
                        ),
                        {"id": target},
                    )
                    == "Target"
                )
                for table in ("ledger_entries", "jobs", "job_outbox", "webhook_deliveries"):
                    count = await session.scalar(
                        select(func.count())
                        .select_from(
                            Base.metadata.tables[table],
                        )
                        .where(Base.metadata.tables[table].c.tenant_id == target)
                    )
                    assert count == 0
            duplicate_run, repeated = await upload()
            assert repeated["state"] == "review", repeated
            repeated_counts = repeated["summary"]["counts"]
            assert repeated_counts["calls"]["duplicate"] == 1
            assert repeated_counts["audio_objects"]["duplicate"] == 1
            assert sum(row["new"] for row in repeated_counts.values()) == 0
            assert (
                await client.delete(f"{route}/import/{duplicate_run}", headers=dst)
            ).status_code == 204
            monkeypatch.setattr(ftp, "public_address", lambda host, port: "8.8.8.8")
            response = await client.put(
                f"{route}/backup/settings",
                headers=src,
                json={
                    "enabled": True,
                    "cadence": "weekly",
                    "local_time": "02:00",
                    "weekday": 5,
                    "destination": {
                        "protocol": "ftps",
                        "host": "backup.example.test",
                        "port": 21,
                        "directory": "/",
                        "username": "test",
                        "password": "fixture-ftp",
                    },
                },
            )
            assert response.status_code == 200, response.text
            assert "fixture-ftp" not in response.text
            async with db.control_session_scope() as session:
                saved = await session.get(OrganizationBackupSettings, source)
                saved.next_run_at = datetime.now(UTC) - timedelta(minutes=1)
            await jobs.schedule_due()
            await jobs.schedule_due()
            assert await jobs.run_one()

            def transient(*args, **kwargs):
                raise ApiError(
                    "org_backup_ftp_failed", "test connection interruption", retryable=True
                )

            async with db.control_session_scope() as session:
                scheduled = (
                    await session.scalars(
                        select(OrganizationDataRun).where(
                            OrganizationDataRun.tenant_id == source,
                            OrganizationDataRun.kind == "scheduled",
                        )
                    )
                ).one()
                assert scheduled.state == "succeeded" and scheduled.transfer_state == "queued"
                original_checksum = scheduled.checksum
                scheduled_id = scheduled.id

            with monkeypatch.context() as interrupted:
                interrupted.setattr(ftp, "transfer", transient)
                for minutes in jobs.RETRY_MINUTES:
                    before = datetime.now(UTC)
                    assert await jobs.run_one()
                    async with db.control_session_scope() as session:
                        scheduled = await session.get(OrganizationDataRun, scheduled_id)
                        assert scheduled.due_at >= before + timedelta(minutes=minutes)
                        assert scheduled.state == "succeeded"
                        assert scheduled.transfer_state == "queued"
                        scheduled.due_at = before

            def recovered(destination, path, filename, **kwargs):
                assert destination.protocol == "ftps"
                assert filename.endswith(suffix)
                assert hashlib.sha256(path.read_bytes()).hexdigest() == original_checksum

            monkeypatch.setattr(ftp, "transfer", recovered)
            assert await jobs.run_one()
            history = (await client.get(f"{route}/runs/{scheduled_id}", headers=src)).json()
            assert history["transfer_state"] == "succeeded"
            assert history["transfer_attempts"] == 3
    finally:
        await db.dispose_engine()
        set_storage(None)
        get_settings.cache_clear()
