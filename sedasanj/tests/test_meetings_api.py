"""Meetings API: route wiring (always) and end-to-end flows (disposable PostgreSQL only)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from meeting_helpers import (
    RecordingQueue,
    Workspace,
    api_client,
    drop_workspace,
    make_workspace,
    pair_token,
    requires_ffprobe,
    sha256,
    wav_bytes,
)
from plan_helpers import requires_postgres, scratch  # noqa: F401  (scratch is a fixture)
from plan_routes import api_routes, dependency_calls, scope_names
from sqlalchemy import select, text

from app import db, deps
from app.models import ApiKey, AudioObject, JalaseNegarRelease, Meeting, MeetingChunk
from app.services import jalase_negar_releases as apks
from app.services.queue import QUEUE_MEETING, set_queue
from app.services.storage import MemoryStorage, set_storage

# --------------------------------------------------------------------------- wiring (no database)


def _routes() -> list:
    return [r for r in api_routes() if r.path.startswith("/v1/meetings")]


def test_app_routes_need_the_meetings_scope_and_a_mobile_token() -> None:
    app_paths = {
        ("GET", "/v1/meetings/config/validate"),
        ("POST", "/v1/meetings/sessions"),
        ("PUT", "/v1/meetings/{meeting_id}/chunks/{seq}"),
        ("PUT", "/v1/meetings/{meeting_id}/transcript"),
        ("POST", "/v1/meetings/{meeting_id}/finish"),
        ("POST", "/v1/meetings/{meeting_id}/cancel"),
        # People and voiceprints synced from the app (tests/test_speaker_profiles.py).
        ("GET", "/v1/meetings/speaker-profiles/changes"),
        ("PUT", "/v1/meetings/speaker-profiles/{client_id}"),
        ("DELETE", "/v1/meetings/speaker-profiles/{client_id}"),
    }
    found = {
        (method, route.path)
        for route in _routes()
        for method in route.methods
        if deps.current_api_key in dependency_calls(route.dependant)
    }
    assert found == app_paths
    for route in _routes():
        if deps.current_api_key in dependency_calls(route.dependant):
            assert scope_names(route) == {"meetings:write"}, route.path
            assert deps.current_user not in dependency_calls(route.dependant), route.path


def test_pair_is_the_only_unauthenticated_meeting_route() -> None:
    public = []
    for route in _routes():
        calls = dependency_calls(route.dependant)
        if not calls & {
            deps.current_api_key,
            deps.current_user,
            deps.current_meeting_actor,
        }:
            public.append(route.path)
    assert public == ["/v1/meetings/devices/pair"]


def test_panel_routes_use_the_user_jwt() -> None:
    panel = [
        route
        for route in _routes()
        if deps.current_user in dependency_calls(route.dependant)
        and route.path != "/v1/meetings/devices/pair"
    ]
    assert {route.path for route in panel} >= {
        "/v1/meetings",
        "/v1/meetings/app-download",
        "/v1/meetings/{meeting_id}",
        "/v1/meetings/{meeting_id}/audio/content",
        "/v1/meetings/{meeting_id}/minutes",
        "/v1/meetings/{meeting_id}/minutes/pdf",
        "/v1/meetings/{meeting_id}/reanalyze",
        "/v1/meetings/{meeting_id}/retry",
        "/v1/meetings/devices/pairing-codes",
        "/v1/meetings/devices",
    }


def test_static_routes_are_declared_before_the_meeting_id_catch_all() -> None:
    order = [(sorted(r.methods)[0], r.path) for r in _routes()]
    for static in (
        "/v1/meetings/devices",
        "/v1/meetings/config/validate",
        "/v1/meetings/app-download",
    ):
        assert order.index(("GET", static)) < order.index(("GET", "/v1/meetings/{meeting_id}"))


# --------------------------------------------------------------------------- end to end


@pytest.fixture()
async def world(
    scratch,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[tuple[httpx.AsyncClient, Workspace, RecordingQueue, MemoryStorage]]:
    from app.config import get_settings
    from app.services import ratelimit

    monkeypatch.setenv("QUEUE_BACKEND", "memory")
    monkeypatch.setenv("STORAGE_BACKEND", "memory")
    monkeypatch.setenv("MEETING_TOKEN_LIMIT", "2")
    monkeypatch.setenv("MEETING_RESERVE_BLOCK_SECONDS", "60")
    monkeypatch.setenv("MEETING_CHUNK_MAX_BYTES", str(2 * 1024 * 1024))
    get_settings.cache_clear()
    ratelimit._memory.clear()
    queue, storage = RecordingQueue(), MemoryStorage()
    set_queue(queue)
    set_storage(storage)
    workspace = await make_workspace()
    try:
        async for client in api_client():
            yield client, workspace, queue, storage
    finally:
        await drop_workspace(workspace)
        set_queue(None)
        set_storage(None)
        get_settings.cache_clear()


@requires_postgres
async def test_app_download_uses_the_latest_published_release(world) -> None:
    client, workspace, _queue, storage = world
    path = "/v1/meetings/app-download"
    payload = b"apk contents"
    releases = [
        JalaseNegarRelease(
            id=uuid4(),
            version_name=f"2.0.{code}",
            version_code=code,
            status=state,
            package_name=apks.PACKAGE_NAME,
            min_sdk=24,
            title="Test release",
            artifact_key=f"test-app/{uuid4()}.apk",
            artifact_size=len(payload),
            artifact_sha256=sha256(payload),
            signing_cert_sha256="a" * 64,
        )
        for code, state in enumerate(("published", "published", "revoked", "draft"), start=1)
    ]
    async with db.control_session_scope() as session:
        session.add_all(releases)
    try:
        assert (await client.get(path)).status_code == 401
        latest = releases[1]
        missing = await client.get(path, headers=workspace.operator)
        assert missing.status_code == 503
        assert missing.json()["error"]["code"] == "release_file_unavailable"

        await storage.put(latest.artifact_key, payload, apks.APK_MIME)
        response = await client.get(path, headers=workspace.operator)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        download_path = response.json()["download_path"]
        assert download_path == f"/v1/jalase-negar/android/releases/{latest.id}/download"
        apk = await client.get(download_path)
        assert apk.content == payload
        assert apk.headers["content-type"] == apks.APK_MIME
        assert apk.headers["content-disposition"] == 'attachment; filename="jalase-negar-2.0.2.apk"'

        async with db.control_session_scope() as session:
            for release in releases[:2]:
                stored = await session.get(JalaseNegarRelease, release.id)
                assert stored is not None
                stored.status = "revoked"
        assert (await client.get(download_path)).status_code == 404
        empty = await client.get(path, headers=workspace.admin)
        assert empty.status_code == 404
        assert empty.json()["error"]["code"] == "jalase_negar_release_not_found"
    finally:
        async with db.control_session_scope() as session:
            for release in releases:
                await session.delete(release)


def _session_body(client_id: UUID | None = None, **extra: object) -> dict[str, object]:
    return {
        "client_meeting_id": str(client_id or uuid4()),
        "title": "جلسه تست",
        "started_at": datetime.now(UTC).isoformat(),
        "sample_rate": 16000,
        "channels": 1,
        "app_version": "2.0.0",
        **extra,
    }


async def _put(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    meeting_id: str,
    seq: int,
    audio: bytes,
    *,
    sha: str | None = None,
    start: int = 0,
    device_text: object | None = None,
) -> httpx.Response:
    data = {
        "t_start_ms": str(start),
        "t_end_ms": str(start + 1000),
        "sha256": sha or sha256(audio),
    }
    if device_text is not None:
        data["device_text"] = json.dumps(device_text)
    return await client.put(
        f"/v1/meetings/{meeting_id}/chunks/{seq}",
        headers=headers,
        data=data,
        files={"audio": ("chunk.wav", audio, "audio/wav")},
    )


async def _balance(workspace: Workspace) -> int:
    from app import db

    async with db.session_scope(staff=True) as session:
        return int(
            (
                await session.execute(
                    text("SELECT seconds FROM tenant_balance_cache WHERE tenant_id = :t"),
                    {"t": workspace.tenant_id},
                )
            ).scalar_one()
        )


@requires_postgres
async def test_pairing_hands_out_one_token_per_code_and_enforces_the_device_limit(world) -> None:
    client, workspace, _queue, _storage = world
    headers = workspace.admin

    created = await client.post(
        "/v1/meetings/devices/pairing-codes", json={"label": "گوشی"}, headers=headers
    )
    assert created.status_code == 201
    code = created.json()["pairing_code"]
    assert len(code) == 8 and created.json()["server_url"]

    body = {
        "pairing_code": code.lower(),
        "device_label": "Pixel 8",
        "app_version": "2.0.0",
        "platform": "android",
    }
    paired = await client.post("/v1/meetings/devices/pair", json=body)
    assert paired.status_code == 201
    token = paired.json()["token"]
    assert token.startswith("sk_live_")
    assert paired.json()["user"] == {"display_name": "Admin"}
    assert paired.json()["limits"]["chunk_max_bytes"] == 2 * 1024 * 1024

    reuse = await client.post("/v1/meetings/devices/pair", json=body)
    assert reuse.status_code == 400
    assert reuse.json()["error"]["code"] == "meeting_pairing_invalid"

    validated = await client.get(
        "/v1/meetings/config/validate", headers={"Authorization": f"Bearer {token}"}
    )
    assert validated.status_code == 200 and validated.json()["ok"] is True

    # The plaintext token is never stored; only its hash and prefix are.
    async with __import__("app.db", fromlist=["x"]).session_scope(staff=True) as session:
        row = (
            await session.execute(select(ApiKey).where(ApiKey.tenant_id == workspace.tenant_id))
        ).scalar_one()
    assert row.kind == "mobile" and row.user_id == workspace.admin_id
    assert row.scopes == ["meetings:write"]
    assert token not in (row.key_hash, row.key_prefix)

    await pair_token(client, headers)
    third = await client.post("/v1/meetings/devices/pairing-codes", json={}, headers=headers)
    refused = await client.post(
        "/v1/meetings/devices/pair",
        json={**body, "pairing_code": third.json()["pairing_code"]},
    )
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "meeting_token_limit"


@requires_postgres
async def test_expired_unknown_and_revoked_credentials_are_refused(world) -> None:
    from app import db
    from app.models import MeetingPairingCode

    client, workspace, _queue, _storage = world
    created = await client.post(
        "/v1/meetings/devices/pairing-codes", json={}, headers=workspace.admin
    )
    async with db.session_scope(staff=True) as session:
        await session.execute(
            text("UPDATE meeting_pairing_codes SET expires_at = :e WHERE tenant_id = :t"),
            {"e": datetime.now(UTC) - timedelta(minutes=1), "t": workspace.tenant_id},
        )
    body = {"device_label": "x", "app_version": "1", "platform": "ios"}
    expired = await client.post(
        "/v1/meetings/devices/pair", json={**body, "pairing_code": created.json()["pairing_code"]}
    )
    unknown = await client.post(
        "/v1/meetings/devices/pair", json={**body, "pairing_code": "ZZZZZZZZ"}
    )
    assert (
        expired.json()["error"]["code"]
        == unknown.json()["error"]["code"]
        == "meeting_pairing_invalid"
    )
    assert MeetingPairingCode.__tablename__ == "meeting_pairing_codes"

    headers = await pair_token(client, workspace.admin)
    listing = await client.get("/v1/meetings/devices", headers=workspace.admin)
    device = listing.json()["items"][0]
    assert device["label"] == "Pixel" and "token" not in device
    assert (
        await client.delete(f"/v1/meetings/devices/{device['id']}", headers=workspace.admin)
    ).status_code == 204
    revoked = await client.get("/v1/meetings/config/validate", headers=headers)
    assert revoked.status_code == 401
    # Another user cannot revoke it either way.
    again = await client.delete(f"/v1/meetings/devices/{device['id']}", headers=workspace.operator)
    assert again.status_code == 404


@requires_postgres
async def test_integration_keys_and_jwts_cannot_use_the_app_routes(world) -> None:
    from app import db
    from app.security import generate_api_key

    client, workspace, _queue, _storage = world
    secret, prefix, key_hash = generate_api_key()
    async with db.session_scope(staff=True) as session:
        session.add(
            ApiKey(
                tenant_id=workspace.tenant_id,
                key_hash=key_hash,
                key_prefix=prefix,
                scopes=["ingest:write", "meetings:write"],
            )
        )
    forged = await client.post(
        "/v1/meetings/sessions", json=_session_body(), headers={"Authorization": f"Bearer {secret}"}
    )
    assert forged.status_code == 403
    assert forged.json()["error"]["code"] == "api_key_scope_denied"
    by_jwt = await client.post(
        "/v1/meetings/sessions", json=_session_body(), headers=workspace.admin
    )
    assert by_jwt.status_code == 401


@requires_postgres
async def test_session_is_idempotent_reserves_credit_and_hides_other_owners(world) -> None:
    client, workspace, _queue, _storage = world
    admin_app = await pair_token(client, workspace.admin)
    operator_app = await pair_token(client, workspace.operator)
    before = await _balance(workspace)
    body = _session_body()

    first = await client.post("/v1/meetings/sessions", json=body, headers=admin_app)
    assert first.status_code == 201
    assert first.json()["status"] == "receiving" and first.json()["received_seqs"] == []
    assert await _balance(workspace) == before - 60

    again = await client.post("/v1/meetings/sessions", json=body, headers=admin_app)
    assert again.status_code == 200
    assert again.json()["meeting_id"] == first.json()["meeting_id"]
    assert await _balance(workspace) == before - 60

    stolen = await client.post("/v1/meetings/sessions", json=body, headers=operator_app)
    assert stolen.status_code == 404
    assert stolen.json()["error"]["code"] == "meeting_not_found"


@requires_postgres
async def test_session_needs_minimum_credit(world, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings

    client, _workspace, _queue, _storage = world
    poor = await make_workspace(minutes=5)
    try:
        monkeypatch.setenv("MEETING_MIN_BALANCE_SECONDS", "600")
        get_settings.cache_clear()
        headers = await pair_token(client, poor.admin)
        refused = await client.post("/v1/meetings/sessions", json=_session_body(), headers=headers)
        assert refused.status_code == 402
        assert refused.json()["error"]["code"] == "insufficient_credit"
    finally:
        await drop_workspace(poor)


@requires_postgres
@requires_ffprobe
async def test_chunks_are_idempotent_validated_and_queued_once(world) -> None:
    from app import db

    client, workspace, queue, storage = world
    headers = await pair_token(client, workspace.admin)
    meeting_id = (
        await client.post("/v1/meetings/sessions", json=_session_body(), headers=headers)
    ).json()["meeting_id"]
    audio = wav_bytes(2)

    stored = await _put(
        client,
        headers,
        meeting_id,
        0,
        audio,
        device_text=[{"t_start_ms": 0, "t_end_ms": 900, "text": "سلام"}],
    )
    assert stored.status_code == 200 and stored.json() == {"seq": 0, "status": "received"}
    assert len(queue.jobs) == 1
    queue_name, function, payload = queue.jobs[0]
    assert (queue_name, function) == (QUEUE_MEETING, "transcribe_meeting_chunk")
    assert payload["meeting_id"] == meeting_id
    assert queue.job_ids == [f"meeting-chunk:{payload['chunk_id']}"]

    async with db.session_scope(workspace.tenant_id) as session:
        chunk = (await session.execute(select(MeetingChunk))).scalar_one()
        audio_row = await session.get(AudioObject, chunk.audio_id)
        meeting = await session.get(Meeting, UUID(meeting_id))
    assert chunk.status == "queued" and chunk.device_text[0]["text"] == "سلام"
    assert audio_row is not None and audio_row.object_key in storage.objects
    assert audio_row.object_key == f"{workspace.tenant_id}/meetings/{meeting_id}/0.wav"
    # Retention follows the tenant's audio_retention_days (30 here).
    assert audio_row.expires_at is not None
    assert (
        timedelta(days=29, hours=23)
        < audio_row.expires_at - datetime.now(UTC)
        <= timedelta(days=30)
    )
    assert meeting is not None and meeting.received_chunks == 1 and meeting.received_ms == 2000

    replay = await _put(client, headers, meeting_id, 0, audio)
    assert replay.status_code == 200 and replay.json()["status"] == "queued"
    assert len(queue.jobs) == 1

    other = wav_bytes(3)
    conflict = await _put(client, headers, meeting_id, 0, other)
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "meeting_chunk_conflict"

    wrong_hash = await _put(client, headers, meeting_id, 1, audio, sha="0" * 64)
    assert wrong_hash.status_code == 422
    assert wrong_hash.json()["error"]["code"] == "meeting_chunk_invalid_audio"
    wrong_rate = await _put(client, headers, meeting_id, 1, wav_bytes(1, sample_rate=8000))
    assert wrong_rate.json()["error"]["code"] == "meeting_chunk_invalid_audio"
    not_wav = await _put(client, headers, meeting_id, 1, b"RIFFnope" * 10)
    assert not_wav.json()["error"]["code"] == "meeting_chunk_invalid_audio"
    too_big = await _put(client, headers, meeting_id, 1, wav_bytes(70))
    assert too_big.status_code == 413
    assert too_big.json()["error"]["code"] == "meeting_chunk_too_large"
    bad_text = await _put(client, headers, meeting_id, 1, audio, device_text={"a": 1})
    assert bad_text.status_code == 422
    assert len(queue.jobs) == 1


@requires_postgres
@requires_ffprobe
async def test_enqueue_failure_leaves_the_chunk_for_the_reconciler(world) -> None:
    from app import db

    client, workspace, queue, _storage = world
    headers = await pair_token(client, workspace.admin)
    meeting_id = (
        await client.post("/v1/meetings/sessions", json=_session_body(), headers=headers)
    ).json()["meeting_id"]
    queue.fail = True
    stored = await _put(client, headers, meeting_id, 0, wav_bytes(1))
    assert stored.status_code == 200 and stored.json()["status"] == "received"
    async with db.session_scope(workspace.tenant_id) as session:
        assert (await session.execute(select(MeetingChunk.status))).scalar_one() == "received"

    # An identical retry re-queues it because it is still `received`.
    queue.fail = False
    retried = await _put(client, headers, meeting_id, 0, wav_bytes(1))
    assert retried.status_code == 200
    assert len(queue.jobs) == 1


@requires_postgres
@requires_ffprobe
async def test_finish_lists_missing_chunks_then_closes_the_meeting(world) -> None:
    client, workspace, _queue, _storage = world
    headers = await pair_token(client, workspace.admin)
    meeting_id = (
        await client.post("/v1/meetings/sessions", json=_session_body(), headers=headers)
    ).json()["meeting_id"]
    await _put(client, headers, meeting_id, 0, wav_bytes(1))
    await _put(client, headers, meeting_id, 2, wav_bytes(1), start=2000)

    finish = {"ended_at": datetime.now(UTC).isoformat(), "total_chunks": 3, "duration_ms": 3000}
    missing = await client.post(f"/v1/meetings/{meeting_id}/finish", json=finish, headers=headers)
    assert missing.status_code == 409
    error = missing.json()["error"]
    assert error["code"] == "meeting_incomplete_chunks" and error["missing_seqs"] == [1]

    status_open = await client.get(f"/v1/meetings/{meeting_id}/status", headers=headers)
    assert status_open.json()["status"] == "receiving"
    assert status_open.json()["received_seqs"] == [0, 2]

    await _put(client, headers, meeting_id, 1, wav_bytes(1), start=1000)
    done = await client.post(f"/v1/meetings/{meeting_id}/finish", json=finish, headers=headers)
    assert done.status_code == 202 and done.json()["status"] == "processing"
    again = await client.post(f"/v1/meetings/{meeting_id}/finish", json=finish, headers=headers)
    assert again.status_code == 202

    late = await _put(client, headers, meeting_id, 3, wav_bytes(1), start=3000)
    assert late.status_code == 409 and late.json()["error"]["code"] == "meeting_closed"

    # The panel sees the same meeting through the JWT; an unrelated operator does not.
    as_admin = await client.get(f"/v1/meetings/{meeting_id}/status", headers=workspace.admin)
    assert as_admin.status_code == 200 and as_admin.json()["status"] == "processing"
    hidden = await client.get(f"/v1/meetings/{meeting_id}/status", headers=workspace.operator)
    assert hidden.status_code == 404


@requires_postgres
@requires_ffprobe
async def test_credit_is_reserved_in_blocks_and_released_on_cancel(world) -> None:
    from app import db

    client, workspace, _queue, _storage = world
    headers = await pair_token(client, workspace.admin)
    before = await _balance(workspace)
    meeting_id = (
        await client.post("/v1/meetings/sessions", json=_session_body(), headers=headers)
    ).json()["meeting_id"]
    # 60 s block size: two 40 s chunks need a second block.
    await _put(client, headers, meeting_id, 0, wav_bytes(40))
    async with db.session_scope(workspace.tenant_id) as session:
        assert (await session.get(Meeting, UUID(meeting_id))).reserved_blocks == 1
    await _put(client, headers, meeting_id, 1, wav_bytes(40), start=40000)
    async with db.session_scope(workspace.tenant_id) as session:
        meeting = await session.get(Meeting, UUID(meeting_id))
    assert meeting.reserved_blocks == 2 and meeting.reserved_seconds == 120
    assert await _balance(workspace) == before - 120

    canceled = await client.post(f"/v1/meetings/{meeting_id}/cancel", headers=headers)
    assert canceled.status_code == 200 and canceled.json()["status"] == "canceled"
    assert await _balance(workspace) == before
    repeated = await client.post(f"/v1/meetings/{meeting_id}/cancel", headers=headers)
    assert repeated.status_code == 200
    assert await _balance(workspace) == before
    late = await _put(client, headers, meeting_id, 2, wav_bytes(1), start=80000)
    assert late.json()["error"]["code"] == "meeting_closed"


@requires_postgres
@requires_ffprobe
async def test_out_of_credit_mid_meeting_rejects_new_chunks_but_keeps_old_ones(
    world, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import get_settings

    client, _workspace, _queue, _storage = world
    tight = await make_workspace(minutes=3)
    try:
        monkeypatch.setenv("MEETING_MIN_BALANCE_SECONDS", "60")
        get_settings.cache_clear()
        headers = await pair_token(client, tight.admin)
        meeting_id = (
            await client.post("/v1/meetings/sessions", json=_session_body(), headers=headers)
        ).json()["meeting_id"]
        for seq in range(3):
            assert (
                await _put(client, headers, meeting_id, seq, wav_bytes(50), start=seq * 50000)
            ).status_code == 200
        refused = await _put(client, headers, meeting_id, 3, wav_bytes(50), start=150000)
        assert refused.status_code == 402
        assert refused.json()["error"]["code"] == "insufficient_credit"
        status = await client.get(f"/v1/meetings/{meeting_id}/status", headers=headers)
        assert status.json()["received_seqs"] == [0, 1, 2]
    finally:
        await drop_workspace(tight)


@requires_postgres
@requires_ffprobe
async def test_panel_visibility_edit_and_delete(world) -> None:
    from app import db

    client, workspace, _queue, storage = world
    admin_app = await pair_token(client, workspace.admin)
    operator_app = await pair_token(client, workspace.operator)
    mine = (
        await client.post(
            "/v1/meetings/sessions", json=_session_body(title="admin"), headers=admin_app
        )
    ).json()["meeting_id"]
    theirs = (
        await client.post(
            "/v1/meetings/sessions", json=_session_body(title="operator"), headers=operator_app
        )
    ).json()["meeting_id"]
    await _put(client, operator_app, theirs, 0, wav_bytes(1))

    admin_list = (await client.get("/v1/meetings", headers=workspace.admin)).json()
    assert admin_list["total"] == 2 and {i["title"] for i in admin_list["items"]} == {
        "admin",
        "operator",
    }
    operator_list = (await client.get("/v1/meetings", headers=workspace.operator)).json()
    assert [i["id"] for i in operator_list["items"]] == [theirs]
    assert operator_list["items"][0]["owner_name"] == "Operator"

    only_admin = await client.get(
        "/v1/meetings", params={"owner_id": str(workspace.admin_id)}, headers=workspace.admin
    )
    assert [i["id"] for i in only_admin.json()["items"]] == [mine]
    forbidden = await client.get(
        "/v1/meetings", params={"owner_id": str(workspace.admin_id)}, headers=workspace.operator
    )
    assert forbidden.status_code == 403
    searched = await client.get("/v1/meetings", params={"q": "oper%"}, headers=workspace.admin)
    assert searched.json()["total"] == 0
    by_status = await client.get(
        "/v1/meetings", params={"status": "receiving", "page_size": 1}, headers=workspace.admin
    )
    assert by_status.json()["pages"] == 2

    assert (await client.get(f"/v1/meetings/{mine}", headers=workspace.operator)).status_code == 404
    detail = await client.get(f"/v1/meetings/{theirs}", headers=workspace.operator)
    assert detail.status_code == 200
    assert detail.json()["segments"] == [] and detail.json()["audio_available"] is False
    assert detail.json()["processing_events"][0]["step_key"] == "receiving"

    renamed = await client.patch(
        f"/v1/meetings/{theirs}", json={"title": "  عنوان تازه "}, headers=workspace.admin
    )
    assert renamed.status_code == 200 and renamed.json()["title"] == "عنوان تازه"
    no_speaker = await client.patch(
        f"/v1/meetings/{theirs}",
        json={"speakers": [{"speaker_idx": 0, "label": "x"}]},
        headers=workspace.admin,
    )
    assert no_speaker.status_code == 422

    before = await _balance(workspace)
    gone = await client.delete(f"/v1/meetings/{theirs}", headers=workspace.operator)
    assert gone.status_code == 204
    assert await _balance(workspace) == before + 60
    assert (await client.get(f"/v1/meetings/{theirs}", headers=workspace.admin)).status_code == 404
    assert not [k for k in storage.objects if str(theirs) in k]
    async with db.session_scope(workspace.tenant_id) as session:
        assert (await session.execute(select(MeetingChunk))).first() is None
        actions = (
            (
                await session.execute(
                    text("SELECT action FROM audit_events WHERE tenant_id = :t"),
                    {"t": workspace.tenant_id},
                )
            )
            .scalars()
            .all()
        )
    assert {"meeting.update", "meeting.delete"} <= set(actions)


@requires_postgres
async def test_another_tenant_cannot_see_a_meeting(world) -> None:
    client, workspace, _queue, _storage = world
    admin_app = await pair_token(client, workspace.admin)
    meeting_id = (
        await client.post("/v1/meetings/sessions", json=_session_body(), headers=admin_app)
    ).json()["meeting_id"]
    other = await make_workspace()
    try:
        assert (
            await client.get(f"/v1/meetings/{meeting_id}", headers=other.admin)
        ).status_code == 404
        assert (await client.get("/v1/meetings", headers=other.admin)).json()["total"] == 0
        assert (
            await client.delete(f"/v1/meetings/{meeting_id}", headers=other.admin)
        ).status_code == 404
        other_app = await pair_token(client, other.admin)
        assert (
            await client.get(f"/v1/meetings/{meeting_id}/status", headers=other_app)
        ).status_code == 404
    finally:
        await drop_workspace(other)


@requires_postgres
async def test_audio_content_supports_ranges_and_disappears_with_retention(world) -> None:
    from app import db

    client, workspace, _queue, storage = world
    app_headers = await pair_token(client, workspace.admin)
    meeting_id = (
        await client.post("/v1/meetings/sessions", json=_session_body(), headers=app_headers)
    ).json()["meeting_id"]
    assert (
        await client.get(f"/v1/meetings/{meeting_id}/audio/content", headers=workspace.admin)
    ).status_code == 404

    body = bytes(range(256)) * 4
    key = f"{workspace.tenant_id}/meetings/{meeting_id}/full.wav"
    storage.objects[key] = body
    async with db.session_scope(workspace.tenant_id) as session:
        audio = AudioObject(
            tenant_id=workspace.tenant_id,
            bucket="audio",
            object_key=key,
            sha256=sha256(body),
            bytes=len(body),
            sample_rate=16000,
            channels=1,
            duration_ms=1,
        )
        session.add(audio)
        await session.flush()
        (await session.get(Meeting, UUID(meeting_id))).audio_id = audio.id

    whole = await client.get(f"/v1/meetings/{meeting_id}/audio/content", headers=workspace.admin)
    assert whole.status_code == 200 and whole.content == body
    assert whole.headers["accept-ranges"] == "bytes"
    part = await client.get(
        f"/v1/meetings/{meeting_id}/audio/content",
        headers={**workspace.admin, "Range": "bytes=10-19"},
    )
    assert part.status_code == 206 and part.content == body[10:20]
    assert part.headers["content-range"] == f"bytes 10-19/{len(body)}"
    tail = await client.get(
        f"/v1/meetings/{meeting_id}/audio/content",
        headers={**workspace.admin, "Range": "bytes=-5"},
    )
    assert tail.content == body[-5:]
    assert (await client.get(f"/v1/meetings/{meeting_id}", headers=workspace.admin)).json()[
        "audio_available"
    ] is True

    async with db.session_scope(workspace.tenant_id) as session:
        (await session.get(AudioObject, audio.id)).deleted_at = datetime.now(UTC)
    gone = await client.get(f"/v1/meetings/{meeting_id}/audio/content", headers=workspace.admin)
    assert gone.status_code == 404


def _transcript(*texts: str) -> dict[str, object]:
    return {
        "asr_identity": "test",
        "segments": [
            {"t_start_ms": i * 2000, "t_end_ms": i * 2000 + 1500, "text": text}
            for i, text in enumerate(texts)
        ],
    }


@requires_postgres
async def test_text_meeting_takes_a_transcript_and_queues_the_minutes(world) -> None:
    from app import db
    from app.models import MeetingSegment
    from app.services.queue import JOB_MEETING_MINUTES

    client, workspace, queue, _storage = world
    headers = await pair_token(client, workspace.admin)
    created = await client.post(
        "/v1/meetings/sessions", json=_session_body(input_kind="text"), headers=headers
    )
    assert created.status_code == 201 and created.json()["input_kind"] == "text"
    meeting_id = created.json()["meeting_id"]

    early = await client.post(
        f"/v1/meetings/{meeting_id}/finish",
        json={"ended_at": datetime.now(UTC).isoformat(), "total_chunks": 0, "duration_ms": 5000},
        headers=headers,
    )
    assert early.status_code == 409
    assert early.json()["error"]["code"] == "meeting_transcript_missing"

    # Audio rides along for playback but is never queued for transcription.
    audio = await _put(client, headers, meeting_id, 0, wav_bytes(1))
    assert audio.status_code == 200
    assert not [job for job in queue.jobs if job[1] == "transcribe_meeting_chunk"]

    body = _transcript("سلام به همه", "بودجه را تأیید کردیم")
    stored = await client.put(f"/v1/meetings/{meeting_id}/transcript", json=body, headers=headers)
    assert stored.status_code == 200 and stored.json()["segments"] == 2
    assert stored.json()["replay"] is False
    replay = await client.put(f"/v1/meetings/{meeting_id}/transcript", json=body, headers=headers)
    assert replay.json()["replay"] is True and replay.json()["sha256"] == stored.json()["sha256"]

    changed = _transcript("متن اصلاح‌شده")
    await client.put(f"/v1/meetings/{meeting_id}/transcript", json=changed, headers=headers)
    async with db.session_scope(workspace.tenant_id) as session:
        rows = (await session.execute(select(MeetingSegment))).scalars().all()
    assert [row.text for row in rows] == ["متن اصلاح‌شده"]
    assert {row.source for row in rows} == {"device_asr"}

    backwards = _transcript("الف", "ب")
    backwards["segments"][1]["t_start_ms"] = 0  # type: ignore[index]
    backwards["segments"][0]["t_start_ms"] = 5000  # type: ignore[index]
    refused = await client.put(
        f"/v1/meetings/{meeting_id}/transcript", json=backwards, headers=headers
    )
    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "meeting_transcript_invalid"

    finish = {"ended_at": datetime.now(UTC).isoformat(), "total_chunks": 1, "duration_ms": 90_000}
    done = await client.post(f"/v1/meetings/{meeting_id}/finish", json=finish, headers=headers)
    assert done.status_code == 202 and done.json()["status"] == "processing"
    minutes_jobs = [job for job in queue.jobs if job[1] == JOB_MEETING_MINUTES]
    assert len(minutes_jobs) == 1 and minutes_jobs[0][2]["version"] == 1
    assert len([job for job in queue.jobs if job[1] == "assemble_meeting_audio"]) == 1

    again = await client.post(f"/v1/meetings/{meeting_id}/finish", json=finish, headers=headers)
    assert again.status_code == 202
    assert len([job for job in queue.jobs if job[1] == JOB_MEETING_MINUTES]) == 1

    async with db.session_scope(workspace.tenant_id) as session:
        meeting = await session.get(Meeting, UUID(meeting_id))
    assert meeting is not None and meeting.duration_ms == 90_000 and meeting.received_ms == 90_000


@requires_postgres
async def test_edited_transcript_of_a_complete_meeting_rebuilds_the_minutes(world) -> None:
    from app import db
    from app.models import MeetingSegment
    from app.services.queue import JOB_MEETING_MINUTES

    client, workspace, queue, _storage = world
    headers = await pair_token(client, workspace.admin)
    created = await client.post(
        "/v1/meetings/sessions", json=_session_body(input_kind="text"), headers=headers
    )
    meeting_id = created.json()["meeting_id"]
    first = _transcript("سلام به همه", "بودجه را تأیید کردیم")
    assert (
        await client.put(f"/v1/meetings/{meeting_id}/transcript", json=first, headers=headers)
    ).status_code == 200
    finish = {"ended_at": datetime.now(UTC).isoformat(), "total_chunks": 0, "duration_ms": 5000}
    assert (
        await client.post(f"/v1/meetings/{meeting_id}/finish", json=finish, headers=headers)
    ).status_code == 202

    edited = _transcript("سلام به همه", "بودجه را رد کردیم")
    busy = await client.put(f"/v1/meetings/{meeting_id}/transcript", json=edited, headers=headers)
    assert busy.status_code == 409 and busy.json()["error"]["code"] == "meeting_closed"

    async with db.session_scope(workspace.tenant_id) as session:
        meeting = await session.get(Meeting, UUID(meeting_id))
        assert meeting is not None
        meeting.status = "complete"
    jobs_before = len([job for job in queue.jobs if job[1] == JOB_MEETING_MINUTES])

    same = await client.put(f"/v1/meetings/{meeting_id}/transcript", json=first, headers=headers)
    assert same.status_code == 200 and same.json()["replay"] is True
    assert len([job for job in queue.jobs if job[1] == JOB_MEETING_MINUTES]) == jobs_before

    stored = await client.put(f"/v1/meetings/{meeting_id}/transcript", json=edited, headers=headers)
    assert stored.status_code == 200 and stored.json()["replay"] is False
    assert len([job for job in queue.jobs if job[1] == JOB_MEETING_MINUTES]) == jobs_before + 1
    async with db.session_scope(workspace.tenant_id) as session:
        meeting = await session.get(Meeting, UUID(meeting_id))
        rows = (await session.execute(select(MeetingSegment))).scalars().all()
    assert meeting is not None and meeting.status == "processing"
    assert [row.text for row in rows] == ["سلام به همه", "بودجه را رد کردیم"]
