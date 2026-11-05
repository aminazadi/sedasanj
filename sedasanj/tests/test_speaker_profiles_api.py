"""Speaker profiles sync API end to end (needs the disposable PostgreSQL, see plan_helpers)."""

from __future__ import annotations

import asyncio
import base64
import struct
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from cryptography.fernet import Fernet
from meeting_helpers import Workspace, api_client, drop_workspace, make_workspace, pair_token
from plan_helpers import requires_postgres, scratch  # noqa: F401  (scratch is a fixture)
from sqlalchemy import select, text

from app import db
from app.models import MeetingSegment, MeetingSpeaker, SpeakerProfile, SpeakerVoiceprint

BASE = "/v1/meetings/speaker-profiles"
CONSENT = {"at": "2026-11-01T10:00:00+00:00", "version": "2026-11"}

World = tuple[httpx.AsyncClient, Workspace, dict[str, str], dict[str, str]]


@pytest.fixture()
async def world(
    scratch,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[World]:
    from app.config import get_settings
    from app.services import ratelimit
    from app.services.queue import MemoryQueue, set_queue
    from app.services.storage import MemoryStorage, set_storage

    monkeypatch.setenv("QUEUE_BACKEND", "memory")
    monkeypatch.setenv("STORAGE_BACKEND", "memory")
    monkeypatch.setenv("VOICEPRINT_ENCRYPTION_KEY", Fernet.generate_key().decode())
    get_settings.cache_clear()
    ratelimit._memory.clear()
    set_queue(MemoryQueue())
    set_storage(MemoryStorage())
    workspace = await make_workspace()
    try:
        async for client in api_client():
            admin_phone = await pair_token(client, workspace.admin)
            operator_phone = await pair_token(client, workspace.operator)
            yield client, workspace, admin_phone, operator_phone
    finally:
        await drop_workspace(workspace)
        set_queue(None)
        set_storage(None)
        get_settings.cache_clear()


def _vector(value: float, dim: int = 16) -> bytes:
    return struct.pack(f"<{dim}f", *([value] * dim))


def _sample(value: float = 0.25, *, sample: UUID | None = None, model: str = "campp") -> dict:
    return {
        "client_id": str(sample or uuid4()),
        "model_id": model,
        "model_version": "1",
        "dim": 16,
        "embedding_b64": base64.b64encode(_vector(value)).decode(),
        "quality": 80,
        "duration_ms": 20_000,
    }


def _body(name: str = "سارا", *, base: int = 0, **extra: Any) -> dict[str, Any]:
    return {"display_name": name, "base_version": base, **extra}


async def _changes(client: httpx.AsyncClient, phone: dict[str, str], cursor: int = 0, **q: Any):
    return await client.get(f"{BASE}/changes", params={"cursor": cursor, **q}, headers=phone)


@requires_postgres
async def test_a_new_phone_gets_the_people_and_voiceprints_back(world: World) -> None:
    client, _workspace, phone, _other = world
    cid, sample = uuid4(), _sample(0.5)
    created = await client.put(
        f"{BASE}/{cid}",
        json=_body(consent=CONSENT, voiceprints=[sample]),
        headers=phone,
    )
    assert created.status_code == 200, created.text
    assert created.json()["version"] == 1 and created.json()["mine"] is True

    # A freshly paired phone of the same user starts from cursor 0 and receives everything.
    second_phone = await pair_token(client, _workspace.admin)
    pulled = await _changes(client, second_phone)
    body = pulled.json()
    assert pulled.status_code == 200 and body["has_more"] is False
    [item] = body["items"]
    assert item["client_id"] == str(cid) and item["display_name"] == "سارا"
    assert item["voiceprints"][0]["embedding_b64"] == sample["embedding_b64"]
    assert body["next_cursor"] >= item["change_seq"]
    empty = await _changes(client, second_phone, body["next_cursor"])
    assert empty.json()["items"] == []


@requires_postgres
async def test_voiceprints_are_encrypted_at_rest(world: World) -> None:
    client, workspace, phone, _other = world
    cid = uuid4()
    await client.put(
        f"{BASE}/{cid}", json=_body(consent=CONSENT, voiceprints=[_sample(0.5)]), headers=phone
    )
    async with db.session_scope(workspace.tenant_id) as session:
        stored = (await session.execute(select(SpeakerVoiceprint.embedding))).scalar_one()
    assert _vector(0.5) not in bytes(stored)


@requires_postgres
async def test_resending_the_same_request_changes_nothing_and_a_stale_one_conflicts(
    world: World,
) -> None:
    client, _workspace, phone, _other = world
    cid, sample = uuid4(), _sample()
    body = _body(consent=CONSENT, voiceprints=[sample])
    first = await client.put(f"{BASE}/{cid}", json=body, headers=phone)
    replay = await client.put(f"{BASE}/{cid}", json=body, headers=phone)
    assert replay.status_code == 200
    assert (
        replay.json()["version"] == 1 and replay.json()["change_seq"] == first.json()["change_seq"]
    )

    renamed = await client.put(f"{BASE}/{cid}", json=_body("سارا احمدی", base=1), headers=phone)
    assert renamed.json()["version"] == 2

    stale = await client.put(f"{BASE}/{cid}", json=_body("نام دیگر", base=1), headers=phone)
    assert stale.status_code == 409
    error = stale.json()["error"]
    assert error["code"] == "speaker_profile_conflict"
    assert error["current"]["display_name"] == "سارا احمدی" and error["current"]["version"] == 2


@requires_postgres
async def test_samples_merge_by_id_and_are_removed_only_when_listed(world: World) -> None:
    client, _workspace, phone, _other = world
    cid, one, two = uuid4(), _sample(0.1), _sample(0.2)
    await client.put(f"{BASE}/{cid}", json=_body(consent=CONSENT, voiceprints=[one]), headers=phone)
    merged = await client.put(f"{BASE}/{cid}", json=_body(base=1, voiceprints=[two]), headers=phone)
    ids = {v["client_id"] for v in merged.json()["voiceprints"]}
    assert ids == {one["client_id"], two["client_id"]} and merged.json()["version"] == 2

    removed = await client.put(
        f"{BASE}/{cid}",
        json=_body(base=2, remove_voiceprints=[one["client_id"]]),
        headers=phone,
    )
    assert {v["client_id"] for v in removed.json()["voiceprints"]} == {two["client_id"]}


@requires_postgres
async def test_a_voiceprint_needs_the_persons_consent(world: World) -> None:
    client, _workspace, phone, _other = world
    refused = await client.put(
        f"{BASE}/{uuid4()}", json=_body(voiceprints=[_sample()]), headers=phone
    )
    assert (
        refused.status_code == 422 and refused.json()["error"]["code"] == "speaker_consent_required"
    )
    future = {"at": (datetime.now(UTC) + timedelta(days=3)).isoformat(), "version": "1"}
    bad_clock = await client.put(
        f"{BASE}/{uuid4()}", json=_body(consent=future, voiceprints=[_sample()]), headers=phone
    )
    assert bad_clock.json()["error"]["code"] == "speaker_consent_required"
    # A name alone is not biometric data and needs no consent.
    named = await client.put(f"{BASE}/{uuid4()}", json=_body("علی"), headers=phone)
    assert named.status_code == 200


@requires_postgres
async def test_malformed_voiceprints_are_rejected(world: World) -> None:
    client, _workspace, phone, _other = world
    wrong_length = _sample() | {"dim": 32}
    zeros = _sample(0.0)
    for bad in (wrong_length, zeros, _sample() | {"embedding_b64": "%%%%%%%%"}):
        response = await client.put(
            f"{BASE}/{uuid4()}", json=_body(consent=CONSENT, voiceprints=[bad]), headers=phone
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "speaker_voiceprint_invalid"
    twice = _sample()
    duplicate = await client.put(
        f"{BASE}/{uuid4()}", json=_body(consent=CONSENT, voiceprints=[twice, twice]), headers=phone
    )
    assert duplicate.json()["error"]["code"] == "speaker_voiceprint_invalid"


@requires_postgres
async def test_profiles_are_private_until_shared_and_colleagues_hear_when_sharing_stops(
    world: World,
) -> None:
    client, _workspace, mine, colleague = world
    cid = uuid4()
    await client.put(f"{BASE}/{cid}", json=_body("خصوصی"), headers=mine)
    assert (await _changes(client, colleague)).json()["items"] == []
    stolen = await client.put(f"{BASE}/{cid}", json=_body("هک", base=1), headers=colleague)
    assert stolen.status_code == 404
    assert (await client.delete(f"{BASE}/{cid}", headers=colleague)).status_code == 404

    shared = await client.put(
        f"{BASE}/{cid}", json=_body("خصوصی", base=1, visibility="org"), headers=mine
    )
    [seen] = (await _changes(client, colleague)).json()["items"]
    assert seen["display_name"] == "خصوصی" and seen["mine"] is False and seen["deleted"] is False

    await client.put(
        f"{BASE}/{cid}", json=_body("خصوصی", base=2, visibility="private"), headers=mine
    )
    [gone] = (await _changes(client, colleague, shared.json()["change_seq"])).json()["items"]
    assert gone["deleted"] is True and gone["display_name"] == "" and gone["voiceprints"] == []


@requires_postgres
async def test_delete_erases_the_voiceprints_and_leaves_a_tombstone(world: World) -> None:
    client, workspace, phone, _other = world
    cid = uuid4()
    await client.put(
        f"{BASE}/{cid}", json=_body(consent=CONSENT, voiceprints=[_sample()]), headers=phone
    )
    deleted = await client.delete(f"{BASE}/{cid}", headers=phone)
    assert deleted.status_code == 200 and deleted.json()["deleted"] is True
    assert (await client.delete(f"{BASE}/{cid}", headers=phone)).status_code == 200  # idempotent

    async with db.session_scope(workspace.tenant_id) as session:
        assert (await session.execute(select(SpeakerVoiceprint))).first() is None
        profile = (await session.execute(select(SpeakerProfile))).scalar_one()
        assert profile.deleted_at is not None and profile.consent_at is None

    [tombstone] = (await _changes(client, phone)).json()["items"]
    assert tombstone["deleted"] is True and tombstone["display_name"] == ""
    revive = await client.put(f"{BASE}/{cid}", json=_body("دوباره", base=0), headers=phone)
    assert revive.status_code == 404


@requires_postgres
async def test_changes_page_in_order_and_the_cursor_only_moves_forward(world: World) -> None:
    client, _workspace, phone, _other = world
    ids = [uuid4() for _ in range(5)]
    for index, cid in enumerate(ids):
        await client.put(f"{BASE}/{cid}", json=_body(f"فرد {index}"), headers=phone)

    seen: list[str] = []
    cursor, pages = 0, 0
    while True:
        page = (await _changes(client, phone, cursor, limit=2)).json()
        assert page["next_cursor"] >= cursor
        seen += [item["client_id"] for item in page["items"]]
        cursor, pages = page["next_cursor"], pages + 1
        if not page["has_more"]:
            break
    assert seen == [str(cid) for cid in ids] and pages == 3

    await client.put(f"{BASE}/{ids[0]}", json=_body("تغییر کرد", base=1), headers=phone)
    [changed] = (await _changes(client, phone, cursor)).json()["items"]
    assert changed["client_id"] == str(ids[0]) and changed["display_name"] == "تغییر کرد"


@requires_postgres
async def test_two_phones_creating_the_same_person_at_once_do_not_fail(world: World) -> None:
    client, _workspace, phone, _other = world
    cid = uuid4()
    results = await asyncio.gather(
        *[client.put(f"{BASE}/{cid}", json=_body("هم‌زمان"), headers=phone) for _ in range(4)]
    )
    assert [r.status_code for r in results] == [200] * 4
    assert {r.json()["version"] for r in results} == {1}
    assert len((await _changes(client, phone)).json()["items"]) == 1


@requires_postgres
async def test_limits_are_enforced(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings

    client, _workspace, phone, _other = world
    monkeypatch.setenv("SPEAKER_MAX_PROFILES_PER_USER", "2")
    monkeypatch.setenv("SPEAKER_MAX_VOICEPRINTS_PER_PROFILE", "2")
    get_settings.cache_clear()
    first = uuid4()
    await client.put(f"{BASE}/{first}", json=_body("یک"), headers=phone)
    await client.put(f"{BASE}/{uuid4()}", json=_body("دو"), headers=phone)
    third = await client.put(f"{BASE}/{uuid4()}", json=_body("سه"), headers=phone)
    assert third.status_code == 409 and third.json()["error"]["code"] == "speaker_profile_limit"

    await client.put(
        f"{BASE}/{first}",
        json=_body("یک", base=1, consent=CONSENT, voiceprints=[_sample(0.1), _sample(0.2)]),
        headers=phone,
    )
    over = await client.put(
        f"{BASE}/{first}", json=_body("یک", base=2, voiceprints=[_sample(0.3)]), headers=phone
    )
    assert over.status_code == 409 and over.json()["error"]["code"] == "speaker_profile_limit"


@requires_postgres
async def test_without_the_encryption_key_voiceprints_fail_closed(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import get_settings

    client, _workspace, phone, _other = world
    monkeypatch.setenv("VOICEPRINT_ENCRYPTION_KEY", "")
    get_settings.cache_clear()
    refused = await client.put(
        f"{BASE}/{uuid4()}", json=_body(consent=CONSENT, voiceprints=[_sample()]), headers=phone
    )
    assert refused.status_code == 503
    assert refused.json()["error"]["code"] == "speaker_storage_unavailable"
    assert (
        await client.put(f"{BASE}/{uuid4()}", json=_body("فقط نام"), headers=phone)
    ).status_code == 200


@requires_postgres
async def test_a_voiceprint_copied_onto_another_row_is_not_served(world: World) -> None:
    client, workspace, phone, _other = world
    a, b = uuid4(), uuid4()
    for cid, value in ((a, 0.1), (b, 0.9)):
        await client.put(
            f"{BASE}/{cid}",
            json=_body(consent=CONSENT, voiceprints=[_sample(value)]),
            headers=phone,
        )
    async with db.session_scope(workspace.tenant_id) as session:
        rows = (
            (
                await session.execute(
                    select(SpeakerVoiceprint).order_by(SpeakerVoiceprint.created_at)
                )
            )
            .scalars()
            .all()
        )
        rows[0].embedding = rows[1].embedding
    broken = await _changes(client, phone)
    assert broken.status_code == 503
    assert broken.json()["error"]["code"] == "speaker_storage_unavailable"


@requires_postgres
async def test_another_organisation_sees_nothing(world: World) -> None:
    client, _workspace, phone, _other = world
    await client.put(f"{BASE}/{uuid4()}", json=_body("فرد", visibility="org"), headers=phone)
    stranger = await make_workspace()
    try:
        stranger_phone = await pair_token(client, stranger.admin)
        assert (await _changes(client, stranger_phone)).json()["items"] == []
    finally:
        await drop_workspace(stranger)


@requires_postgres
async def test_old_tombstones_are_purged_but_recent_ones_stay(world: World) -> None:
    from app.services import speaker_profiles

    client, workspace, phone, _other = world
    old, recent = uuid4(), uuid4()
    for cid in (old, recent):
        await client.put(f"{BASE}/{cid}", json=_body(), headers=phone)
        await client.delete(f"{BASE}/{cid}", headers=phone)
    async with db.session_scope(workspace.tenant_id) as session:
        await session.execute(
            text(
                "UPDATE speaker_profiles SET deleted_at = now() - interval '120 days' "
                "WHERE client_id = :c"
            ),
            {"c": old},
        )
        removed = await speaker_profiles.purge_tombstones(session, workspace.tenant_id)
    assert removed == 1
    [left] = (await _changes(client, phone)).json()["items"]
    assert left["client_id"] == str(recent)


def _session_body() -> dict[str, object]:
    return {
        "client_meeting_id": str(uuid4()),
        "title": "جلسه تست",
        "started_at": datetime.now(UTC).isoformat(),
        "sample_rate": 16000,
        "channels": 1,
        "app_version": "2.0.0",
        "input_kind": "text",
    }


@requires_postgres
async def test_a_transcript_carries_names_overlap_and_the_matched_profile(world: World) -> None:
    client, workspace, phone, _other = world
    cid = uuid4()
    await client.put(f"{BASE}/{cid}", json=_body("سارا"), headers=phone)
    meeting = (
        await client.post("/v1/meetings/sessions", json=_session_body(), headers=phone)
    ).json()
    meeting_id = meeting["meeting_id"]
    url = f"/v1/meetings/{meeting_id}/transcript"

    payload = {
        "asr_identity": "test",
        "segments": [
            {
                "t_start_ms": 0,
                "t_end_ms": 2000,
                "text": "سلام",
                "speaker": 0,
                "speaker_confidence": 91,
            },
            {"t_start_ms": 2000, "t_end_ms": 4000, "text": "بله", "speaker": 1, "overlap": True},
            {"t_start_ms": 2000, "t_end_ms": 4000, "text": "بله", "speaker": 0, "overlap": True},
        ],
        "speakers": [
            {"idx": 0, "label": "سارا", "profile_client_id": str(cid)},
            {"idx": 1, "label": "ناشناس ۱"},
        ],
    }
    stored = await client.put(url, json=payload, headers=phone)
    assert stored.status_code == 200 and stored.json()["replay"] is False
    assert (await client.put(url, json=payload, headers=phone)).json()["replay"] is True

    detail = (await client.get(f"/v1/meetings/{meeting_id}", headers=workspace.admin)).json()
    labels = {s["speaker_idx"]: s for s in detail["speakers"]}
    assert labels[0]["label"] == "سارا" and labels[0]["profile_client_id"] == str(cid)
    assert labels[1]["profile_client_id"] is None
    assert [(s["overlap"], s["speaker_confidence"]) for s in detail["segments"]] == [
        (False, 91),
        (True, None),
        (True, None),
    ]

    renamed = {
        **payload,
        "speakers": [
            {"idx": 0, "label": "سارا احمدی", "profile_client_id": str(cid)},
            payload["speakers"][1],
        ],
    }
    again = await client.put(url, json=renamed, headers=phone)
    assert again.json()["replay"] is False

    async with db.session_scope(workspace.tenant_id) as session:
        speakers = (
            (await session.execute(select(MeetingSpeaker).order_by(MeetingSpeaker.speaker_idx)))
            .scalars()
            .all()
        )
        assert [s.label for s in speakers] == ["سارا احمدی", "ناشناس ۱"]
        assert len((await session.execute(select(MeetingSegment))).scalars().all()) == 3

    # Forgetting the person keeps the meeting's printed name; the link points at the tombstone.
    await client.delete(f"{BASE}/{cid}", headers=phone)
    async with db.session_scope(workspace.tenant_id) as session:
        first = (
            await session.execute(select(MeetingSpeaker).where(MeetingSpeaker.speaker_idx == 0))
        ).scalar_one()
        assert first.label == "سارا احمدی" and first.profile_id is not None
