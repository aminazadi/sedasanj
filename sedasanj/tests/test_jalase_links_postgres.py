"""Linking a personal Jalase-Negar account to an organization, and the panel menu."""

from __future__ import annotations

import secrets
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from tests.plan_helpers import make_org, requires_postgres, scratch  # noqa: F401

from app import db
from app.errors import ApiError
from app.models import (
    ApiKey,
    JalaseAccountLink,
    JalaseEarnedAchievement,
    JalaseInviteCode,
    Meeting,
    MeetingDocument,
    MeetingDocumentVersion,
    MeetingMinutes,
    MeetingPairingCode,
    MeetingSegment,
    MeetingSpeaker,
    SpeakerProfile,
    SpeakerVoiceprint,
    Tenant,
    TokenGrant,
    User,
)
from app.routers import jalase_org_menu as menu
from app.routers import meetings as meetings_router
from app.routers.admin_users import UserFilters, users_query
from app.schemas import MeetingPairIn
from app.security import hash_api_key
from app.services import jalase_accounts, jalase_links, ratelimit
from app.services.phone_identity import mobile_accounts

pytestmark = requires_postgres


async def published_category() -> str:
    """A published non-default category created by the test, not borrowed from the database."""
    async with db.session_scope(staff=True) as session:
        await session.execute(
            text(
                "INSERT INTO jalase_output_types (code, title_fa, menu_label_fa, status) "
                "VALUES ('test_links_cat', 'دستهٔ آزمون', 'آزمون', 'published') "
                "ON CONFLICT (code) DO UPDATE SET status = 'published'"
            )
        )
    return "test_links_cat"


TABLES = (
    "speaker_voiceprints",
    "speaker_profiles",
    "jalase_earned_achievements",
    "jalase_xp_events",
    "jalase_invite_codes",
    "meeting_minutes",
    "meeting_speakers",
    "meeting_document_versions",
    "meeting_segments",
    "jalase_menu_hidden",
    "meeting_documents",
    "meetings",
    "api_keys",
    "audit_events",
    "token_grants",
    "ledger_entries",
    "credit_grants",
    "tenant_balance_cache",
    "trial_claims",
    "subscriptions",
    "users",
)


@pytest.fixture(autouse=True)
def no_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    async def allow(*args: object, **kwargs: object) -> None:
        return None

    monkeypatch.setattr(ratelimit, "enforce", allow)


@pytest.fixture()
async def created(scratch: None) -> AsyncIterator[list[UUID]]:  # noqa: F811
    tenants: list[UUID] = []
    yield tenants
    async with db.session_scope(staff=True) as session:
        await session.execute(text("SET LOCAL session_replication_role = replica"))
        for t in tenants:
            await session.execute(
                text(
                    "DELETE FROM jalase_account_links "
                    "WHERE personal_tenant_id = :t OR org_tenant_id = :t"
                ),
                {"t": t},
            )
            await session.execute(
                text("DELETE FROM meeting_pairing_codes WHERE tenant_id = :t"), {"t": t}
            )
            for table in TABLES:
                await session.execute(text(f"DELETE FROM {table} WHERE tenant_id = :t"), {"t": t})
            await session.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": t})


async def personal(created: list[UUID]) -> tuple[UUID, UUID]:
    async with db.session_scope(staff=True) as session:
        tenant, user = await jalase_accounts.create_personal_account(
            session, mobile="09" + str(uuid4().int)[:9], display_name="سارا", ip="127.0.0.1"
        )
        created.append(tenant.id)
        return tenant.id, user.id


async def org(created: list[UUID]) -> tuple[UUID, UUID]:
    made = await make_org()
    created.append(made.tenant_id)
    return made.tenant_id, made.user_id


async def code_for(tenant_id: UUID, user_id: UUID) -> str:
    code = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(10))
    async with db.session_scope(staff=True) as session:
        session.add(
            MeetingPairingCode(
                tenant_id=tenant_id,
                user_id=user_id,
                code_hash=hash_api_key(code),
                expires_at=datetime.now(UTC) + timedelta(minutes=30),
            )
        )
    return code


def payload(code: str) -> MeetingPairIn:
    return MeetingPairIn(
        pairing_code=code, device_label="گوشی", app_version="1.0.0", platform="android"
    )


async def do_link(personal_ids: tuple[UUID, UUID], code: str) -> dict[str, object]:
    async with db.session_scope(staff=True) as session:
        return await jalase_links.link(
            session,
            personal_tenant_id=personal_ids[0],
            personal_user_id=personal_ids[1],
            payload=payload(code),
            ip="127.0.0.1",
        )


async def test_linking_gives_an_organization_key_and_is_listed(created: list[UUID]) -> None:
    me = await personal(created)
    org_ids = await org(created)
    result = await do_link(me, await code_for(*org_ids))
    assert result["token"] and result["link_id"]
    async with db.session_scope(staff=True) as session:
        key = (
            await session.execute(select(ApiKey).where(ApiKey.tenant_id == org_ids[0]))
        ).scalar_one()
        assert key.kind == "mobile" and key.revoked_at is None
        items = await jalase_links.list_links(session, me[0])
    assert [i["id"] for i in items] == [result["link_id"]]
    for wanted, expected in ((True, True), (False, False)):
        async with db.session_scope(staff=True) as session:
            ids = (
                (
                    await session.execute(
                        users_query(
                            UserFilters(product="jalase_negar", linked=wanted)
                        ).with_only_columns(User.id)
                    )
                )
                .scalars()
                .all()
            )
        assert (me[1] in ids) is expected


async def test_a_code_works_once_and_a_second_link_keeps_its_code(created: list[UUID]) -> None:
    me = await personal(created)
    org_ids = await org(created)
    first = await code_for(*org_ids)
    await do_link(me, first)
    with pytest.raises(ApiError) as reused:
        await do_link(me, first)
    assert reused.value.code == "meeting_pairing_invalid"
    second = await code_for(*org_ids)
    with pytest.raises(ApiError) as twice:
        await do_link(me, second)
    assert twice.value.code == "link_already_exists"
    async with db.session_scope(staff=True) as session:
        row = (
            await session.execute(
                select(MeetingPairingCode).where(
                    MeetingPairingCode.code_hash == hash_api_key(second)
                )
            )
        ).scalar_one()
        assert row.used_at is None  # the failed link did not burn the code
        keys = (
            (await session.execute(select(ApiKey).where(ApiKey.tenant_id == org_ids[0])))
            .scalars()
            .all()
        )
        assert len(keys) == 1


async def test_only_sedasanj_organizations_can_be_linked(created: list[UUID]) -> None:
    me = await personal(created)
    other = await personal(created)
    with pytest.raises(ApiError) as refused:
        await do_link(me, await code_for(*other))
    assert refused.value.code == "link_invalid_target"
    async with db.session_scope(staff=True) as session:
        count = (
            (
                await session.execute(
                    select(JalaseAccountLink).where(JalaseAccountLink.personal_tenant_id == me[0])
                )
            )
            .scalars()
            .all()
        )
        assert count == []


async def test_revoking_cuts_the_organization_key_only(created: list[UUID]) -> None:
    me = await personal(created)
    stranger = await personal(created)
    org_ids = await org(created)
    result = await do_link(me, await code_for(*org_ids))
    link_id = UUID(str(result["link_id"]))
    async with db.session_scope(staff=True) as session:
        with pytest.raises(ApiError) as foreign:
            await jalase_links.revoke(session, stranger[0], stranger[1], link_id)
        assert foreign.value.code == "link_not_found"
        await jalase_links.revoke(session, me[0], me[1], link_id)
        key = (
            await session.execute(select(ApiKey).where(ApiKey.tenant_id == org_ids[0]))
        ).scalar_one()
        assert key.revoked_at is not None
        with pytest.raises(ApiError):
            await jalase_links.revoke(session, me[0], me[1], link_id)
        assert await jalase_links.list_links(session, me[0]) == []
    # The personal key is untouched and the account can link again with a new code.
    await do_link(me, await code_for(*org_ids))


async def test_panel_menu_shows_all_published_categories_and_honours_hiding(
    created: list[UUID],
) -> None:
    org_ids = await org(created)
    code = await published_category()
    principal = SimpleNamespace(tenant_id=org_ids[0], id=org_ids[1])
    async with db.session_scope(org_ids[0]) as session:
        # Published categories are listed even before the organization has any document.
        first = (await menu.menu(principal, session))["items"]  # type: ignore[arg-type]
        assert [i["code"] for i in first][:1] == ["minutes"]
    async with db.session_scope(staff=True) as session:
        user_id = (
            await session.execute(select(User.id).where(User.tenant_id == org_ids[0]))
        ).scalar_one()
        meeting = Meeting(
            tenant_id=org_ids[0],
            owner_user_id=user_id,
            client_meeting_id=uuid4(),
            started_at=datetime.now(UTC),
        )
        session.add(meeting)
        await session.flush()
        session.add(
            MeetingDocument(
                tenant_id=org_ids[0],
                meeting_id=meeting.id,
                output_type_code=code,
                output_type_version=1,
                status="done",
            )
        )
    admin = SimpleNamespace(tenant_id=org_ids[0], id=org_ids[1], kind="user", role="org_admin")
    async with db.session_scope(org_ids[0]) as session:
        for wanted, expected in ((code, 1), ("minutes", 0)):
            page = await meetings_router.list_meetings(
                session,
                admin,  # type: ignore[arg-type]
                q=None,
                meeting_status=None,
                owner_id=None,
                date_from=None,
                date_to=None,
                output_type=wanted,
                page=1,
                page_size=25,
            )
            assert page.total == expected
    async with db.session_scope(org_ids[0]) as session:
        shown = await menu.menu(principal, session)  # type: ignore[arg-type]
        assert code in [i["code"] for i in shown["items"]]
        await menu.set_hidden(code, menu.HiddenUpdate(hidden=True), principal, session)  # type: ignore[arg-type]
    async with db.session_scope(org_ids[0]) as session:
        shown = await menu.menu(principal, session)  # type: ignore[arg-type]
        assert code not in [i["code"] for i in shown["items"]] and shown["hidden"] == [code]
        await menu.set_hidden(code, menu.HiddenUpdate(hidden=False), principal, session)  # type: ignore[arg-type]
        with pytest.raises(ApiError):
            await menu.set_hidden(
                "nope_nothing", menu.HiddenUpdate(hidden=True), principal, session
            )  # type: ignore[arg-type]
    async with db.session_scope(org_ids[0]) as session:
        assert code in [i["code"] for i in (await menu.menu(principal, session))["items"]]  # type: ignore[arg-type]


async def test_import_copies_finished_meetings_once_and_refuses_purged(
    created: list[UUID],
) -> None:
    me = await personal(created)
    org_ids = await org(created)
    result = await do_link(me, await code_for(*org_ids))
    link_id = UUID(str(result["link_id"]))
    code = await published_category()
    async with db.session_scope(staff=True) as session:
        good = Meeting(
            tenant_id=me[0],
            owner_user_id=me[1],
            client_meeting_id=uuid4(),
            title="مشاوره",
            status="complete",
            started_at=datetime.now(UTC),
        )
        purged = Meeting(
            tenant_id=me[0],
            owner_user_id=me[1],
            client_meeting_id=uuid4(),
            status="complete",
            started_at=datetime.now(UTC),
        )
        session.add_all([good, purged])
        await session.flush()
        session.add(
            MeetingSegment(
                tenant_id=me[0], meeting_id=good.id, t_start_ms=0, t_end_ms=900, text="سلام"
            )
        )
        session.add(
            MeetingSpeaker(
                tenant_id=me[0], meeting_id=good.id, speaker_idx=1, label="سارا", total_ms=900
            )
        )
        session.add(
            MeetingMinutes(
                tenant_id=me[0],
                meeting_id=good.id,
                version=1,
                content_md="# صورت‌جلسه",
                is_selected=True,
            )
        )
        doc = MeetingDocument(
            tenant_id=me[0],
            meeting_id=good.id,
            output_type_code=code,
            output_type_version=1,
            status="done",
        )
        session.add(doc)
        await session.flush()
        session.add(
            MeetingDocumentVersion(
                tenant_id=me[0],
                document_id=doc.id,
                version=1,
                markdown="# متن",
                source="model",
                is_selected=True,
            )
        )
        good_id, purged_id = good.id, purged.id

    async def run(ids: list[UUID]) -> dict[str, object]:
        return await jalase_links.import_meetings(
            personal_tenant_id=me[0],
            personal_user_id=me[1],
            link_id=link_id,
            meeting_ids=ids,
        )

    with pytest.raises(ApiError) as refused:
        await run([good_id, purged_id])
    assert refused.value.code == "import_document_purged"
    async with db.session_scope(staff=True) as session:
        copies = (
            (await session.execute(select(Meeting).where(Meeting.tenant_id == org_ids[0])))
            .scalars()
            .all()
        )
    assert copies == []  # nothing is written when one meeting is refused

    first = await run([good_id])
    assert first["imported"] == [str(good_id)]
    second = await run([good_id])
    assert second["already_imported"] == [str(good_id)] and second["imported"] == []
    async with db.session_scope(staff=True) as session:
        copy = (
            await session.execute(select(Meeting).where(Meeting.tenant_id == org_ids[0]))
        ).scalar_one()
        texts = (
            (
                await session.execute(
                    select(MeetingSegment.text).where(MeetingSegment.meeting_id == copy.id)
                )
            )
            .scalars()
            .all()
        )
        markdown = (
            await session.execute(
                select(MeetingDocumentVersion.markdown).where(
                    MeetingDocumentVersion.tenant_id == org_ids[0]
                )
            )
        ).scalar_one()
        minutes = (
            await session.execute(
                select(MeetingMinutes.content_md).where(
                    MeetingMinutes.meeting_id == copy.id,
                    MeetingMinutes.is_selected.is_(True),
                )
            )
        ).scalar_one_or_none()
        speakers = (
            (
                await session.execute(
                    select(MeetingSpeaker.label).where(MeetingSpeaker.meeting_id == copy.id)
                )
            )
            .scalars()
            .all()
        )
        original = await session.get(Meeting, good_id)
    assert texts == ["سلام"] and markdown == "# متن" and original is not None
    # The organization copy keeps the minutes and the speaker labels, not just the transcript.
    assert minutes == "# صورت‌جلسه" and speakers == ["سارا"]
    admin = SimpleNamespace(tenant_id=org_ids[0], id=org_ids[1], kind="user", role="org_admin")
    async with db.session_scope(org_ids[0]) as session:
        shown = await menu.meeting_documents(copy.id, admin, session)  # type: ignore[arg-type]
    assert [d["markdown"] for d in shown["items"]] == ["# متن"]
    async with db.session_scope(org_ids[0]) as session:
        with pytest.raises(ApiError):
            await menu.meeting_documents(uuid4(), admin, session)  # type: ignore[arg-type]


async def test_deleting_an_account_closes_everything_and_frees_the_number(
    created: list[UUID],
) -> None:
    me = await personal(created)
    org_ids = await org(created)
    await do_link(me, await code_for(*org_ids))
    async with db.session_scope(staff=True) as session:
        mobile = (await session.get(User, me[1])).mobile_number  # type: ignore[union-attr]
        session.add(
            Meeting(
                tenant_id=me[0],
                owner_user_id=me[1],
                client_meeting_id=uuid4(),
                status="complete",
                started_at=datetime.now(UTC),
            )
        )
        profile = SpeakerProfile(
            tenant_id=me[0],
            owner_user_id=me[1],
            client_id=uuid4(),
            display_name="سارا",
            change_seq=1,
        )
        session.add(profile)
        await session.flush()
        session.add(
            SpeakerVoiceprint(
                tenant_id=me[0],
                profile_id=profile.id,
                client_id=uuid4(),
                model_id="test-model",
                model_version="1",
                dim=16,
                embedding=b"\x00" * 64,
            )
        )
        session.add(
            JalaseEarnedAchievement(
                tenant_id=me[0], achievement_code="first_meeting", reward_tokens=5_000
            )
        )
        session.add(
            TokenGrant(
                tenant_id=me[0],
                source="reward",
                total_tokens=5_000,
                remaining_tokens=5_000,
            )
        )
        session.add(JalaseInviteCode(tenant_id=me[0], code="TESTCODE"))
    await jalase_accounts.delete_account(tenant_id=me[0], user_id=me[1])
    async with db.session_scope(staff=True) as session:
        keys = (
            (await session.execute(select(ApiKey).where(ApiKey.tenant_id == me[0]))).scalars().all()
        )
        assert all(k.revoked_at is not None for k in keys)
        org_key = (
            await session.execute(select(ApiKey).where(ApiKey.tenant_id == org_ids[0]))
        ).scalar_one()
        assert org_key.revoked_at is not None
        assert (await session.get(Tenant, me[0])).status == "deleted"  # type: ignore[union-attr]
        assert (
            await session.execute(select(Meeting).where(Meeting.tenant_id == me[0]))
        ).first() is None
        assert (await jalase_links.list_links(session, me[0])) == []
        assert await mobile_accounts(session, str(mobile), product="jalase_negar") == []
        # Nothing that identifies the person or pays them survives the deletion.
        assert (
            await session.execute(select(SpeakerProfile).where(SpeakerProfile.tenant_id == me[0]))
        ).first() is None
        assert (
            await session.execute(
                select(SpeakerVoiceprint).where(SpeakerVoiceprint.tenant_id == me[0])
            )
        ).first() is None
        assert (
            await session.execute(
                select(JalaseEarnedAchievement).where(JalaseEarnedAchievement.tenant_id == me[0])
            )
        ).first() is None
        assert (
            await session.execute(select(TokenGrant).where(TokenGrant.tenant_id == me[0]))
        ).first() is None
        assert (
            await session.execute(
                select(JalaseInviteCode).where(JalaseInviteCode.tenant_id == me[0])
            )
        ).first() is None
