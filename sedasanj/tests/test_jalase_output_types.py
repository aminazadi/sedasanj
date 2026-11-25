"""Jalase-Negar output types: input-field validation (pure) and the admin lifecycle (PostgreSQL)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from tests.plan_helpers import requires_postgres, scratch  # noqa: F401

from app import db
from app.errors import ERROR_STATUS, ApiError
from app.models import HelpMedia, JalaseOutputType, StaffUser
from app.routers import admin_jalase_output_types as admin
from app.services import jalase_output_types as types

REQUEST = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))


def test_input_fields_are_cleaned_and_checked() -> None:
    fields = types.normalize_input_fields(
        [
            {"key": "course", "label_fa": " نام درس ", "type": "text", "required": True},
            {"key": "level", "label_fa": "سطح", "type": "select", "options": ["الف", "ب"]},
        ]
    )
    assert fields[0]["label_fa"] == "نام درس"
    assert fields[0]["required"] is True
    assert fields[1]["options"] == ["الف", "ب"]


@pytest.mark.parametrize(
    "bad",
    [
        [{"key": "Bad Key", "label_fa": "x", "type": "text"}],
        [
            {"key": "a", "label_fa": "x", "type": "text"},
            {"key": "a", "label_fa": "y", "type": "text"},
        ],
        [{"key": "a", "label_fa": "", "type": "text"}],
        [{"key": "a", "label_fa": "x", "type": "file"}],
        [{"key": "a", "label_fa": "x", "type": "select", "options": ["only-one"]}],
        [{"key": f"k{i}", "label_fa": "x", "type": "text"} for i in range(9)],
        "not a list",
    ],
)
def test_bad_input_fields_are_rejected(bad: object) -> None:
    with pytest.raises(ApiError) as caught:
        types.normalize_input_fields(bad)
    assert caught.value.code == "output_type_invalid"


def test_summarize_needs_a_map_instruction_and_transform_does_not() -> None:
    with pytest.raises(ApiError):
        types.check_prompt("summarize", "  ", "prompt")
    types.check_prompt("transform", "", "prompt")


def test_error_codes_have_statuses() -> None:
    for code in (
        "output_type_not_found",
        "output_type_code_taken",
        "output_type_builtin_locked",
        "output_type_invalid",
        "output_type_icon_invalid",
        "output_type_not_publishable",
    ):
        assert code in ERROR_STATUS


@pytest.fixture()
async def cleanup(scratch: None) -> AsyncIterator[list[str]]:  # noqa: F811
    codes: list[str] = []
    yield codes
    async with db.session_scope(staff=True) as session:
        await session.execute(text("DELETE FROM staff_users WHERE email LIKE 'jn-test-%'"))
        for code in codes:
            await session.execute(
                text("DELETE FROM jalase_output_types WHERE code = :c"), {"c": code}
            )
        await session.execute(text("DELETE FROM help_media WHERE filename LIKE 'jn-test-%'"))
        await session.execute(
            text("DELETE FROM audit_events WHERE action LIKE 'jalase.output_type.%'")
        )


@pytest.fixture()
async def admin_staff(cleanup: list[str]) -> SimpleNamespace:  # noqa: ARG001
    async with db.session_scope(staff=True) as session:
        row = StaffUser(
            email=f"jn-test-{uuid4().hex[:8]}@example.com", password_hash="x", role="super_admin"
        )
        session.add(row)
        await session.flush()
        return SimpleNamespace(id=row.id)


def _code() -> str:
    return "t_" + uuid4().hex[:8]


@requires_postgres
async def test_seed_has_a_published_builtin_minutes_type_and_draft_categories(
    scratch: None,  # noqa: F811
) -> None:
    async with db.session_scope(staff=True) as session:
        catalog = await types.published_catalog(session)
        minutes = next(item for item in catalog if item["code"] == "minutes")
        assert minutes["menu_label"] == "صورت‌جلسات عمومی"
        drafts = (
            (
                await session.execute(
                    select(JalaseOutputType.code).where(JalaseOutputType.status == "draft")
                )
            )
            .scalars()
            .all()
        )
    assert {"counseling", "hawza_lecture", "university_notes", "clean_text"} <= set(drafts)
    # Drafts are not offered to users.
    assert "counseling" not in {item["code"] for item in catalog}


@requires_postgres
def test_menu_icon_is_limited_to_the_allowed_list() -> None:
    assert admin._checked_icon("brain") == "brain"
    assert types.DEFAULT_MENU_ICON in types.MENU_ICONS
    with pytest.raises(ApiError) as caught:
        admin._checked_icon("<script>")
    assert caught.value.code == "output_type_icon_invalid"


async def test_create_draft_publish_new_version_and_archive(
    cleanup: list[str], admin_staff: SimpleNamespace
) -> None:
    code = _code()
    cleanup.append(code)
    admin_user = admin_staff
    async with db.session_scope(staff=True) as session:
        created = await admin.create_type(
            admin.TypeCreate(code=code, title_fa="دستهٔ آزمایشی", menu_label_fa="آزمایشی"),
            REQUEST,
            admin_user,
            session,
        )
    type_id = created["id"]
    assert created["status"] == "draft"
    assert created["versions"][0]["state"] == "draft"

    async with db.session_scope(staff=True) as session:
        with pytest.raises(ApiError) as caught:
            await admin.publish(type_id, REQUEST, admin_user, session)  # empty prompt
        assert caught.value.code == "output_type_not_publishable"
        await admin.save_draft(
            type_id,
            admin.DraftUpdate(
                mode="summarize",
                map_instruction="خلاصه کن",
                system_prompt="نسخهٔ یک",
                input_fields=[{"key": "course", "label_fa": "درس", "type": "text"}],
            ),
            REQUEST,
            admin_user,
            session,
        )
        published = await admin.publish(type_id, REQUEST, admin_user, session)
    assert published["status"] == "published"
    assert [v["state"] for v in published["versions"]] == ["published"]

    async with db.session_scope(staff=True) as session:
        catalog = {item["code"]: item for item in await types.published_catalog(session)}
    assert catalog[code]["version"] == 1
    assert catalog[code]["input_fields"][0]["key"] == "course"

    # A change is a new draft; the published text stays untouched until it is published.
    async with db.session_scope(staff=True) as session:
        edited = await admin.save_draft(
            type_id,
            admin.DraftUpdate(system_prompt="نسخهٔ دو"),
            REQUEST,
            admin_user,
            session,
        )
        assert {v["version"]: v["state"] for v in edited["versions"]} == {
            1: "published",
            2: "draft",
        }
        assert edited["versions"][1]["system_prompt"] == "نسخهٔ یک"
    async with db.session_scope(staff=True) as session:
        catalog = {item["code"]: item for item in await types.published_catalog(session)}
        assert catalog[code]["version"] == 1
        republished = await admin.publish(type_id, REQUEST, admin_user, session)
    assert {v["version"]: v["state"] for v in republished["versions"]} == {
        1: "superseded",
        2: "published",
    }

    async with db.session_scope(staff=True) as session:
        archived = await admin.archive(type_id, REQUEST, admin_user, session)
        assert archived["status"] == "archived"
        catalog = {item["code"] for item in await types.published_catalog(session)}
    assert code not in catalog


@requires_postgres
async def test_code_must_be_unique_and_builtin_is_locked(
    cleanup: list[str], admin_staff: SimpleNamespace
) -> None:
    code = _code()
    cleanup.append(code)
    admin_user = admin_staff
    async with db.session_scope(staff=True) as session:
        await admin.create_type(
            admin.TypeCreate(code=code, title_fa="یک", menu_label_fa="یک"),
            REQUEST,
            admin_user,
            session,
        )
    async with db.session_scope(staff=True) as session:
        with pytest.raises(ApiError) as caught:
            await admin.create_type(
                admin.TypeCreate(code=code, title_fa="دو", menu_label_fa="دو"),
                REQUEST,
                admin_user,
                session,
            )
        assert caught.value.code == "output_type_code_taken"
    async with db.session_scope(staff=True) as session:
        minutes = (
            await session.execute(
                select(JalaseOutputType).where(JalaseOutputType.code == "minutes")
            )
        ).scalar_one()
        with pytest.raises(ApiError) as locked:
            await admin.save_draft(
                str(minutes.id), admin.DraftUpdate(system_prompt="x"), REQUEST, admin_user, session
            )
        assert locked.value.code == "output_type_builtin_locked"
        with pytest.raises(ApiError) as no_archive:
            await admin.archive(str(minutes.id), REQUEST, admin_user, session)
        assert no_archive.value.code == "output_type_builtin_locked"
        # Title, description and thumbnail of the built-in type stay editable.
        updated = await admin.update_type(
            str(minutes.id), admin.TypeUpdate(sort_order=10), REQUEST, admin_user, session
        )
        assert updated["builtin"] is True


@requires_postgres
async def test_thumbnail_must_be_an_image_from_the_media_library(
    cleanup: list[str], admin_staff: SimpleNamespace
) -> None:
    code = _code()
    cleanup.append(code)
    admin_user = admin_staff
    async with db.session_scope(staff=True) as session:
        image = HelpMedia(
            kind="image",
            object_key=f"help-media/jn-test-{uuid4()}.png",
            filename="jn-test-image.png",
            content_type="image/png",
            size_bytes=10,
        )
        video = HelpMedia(
            kind="video",
            object_key=f"help-media/jn-test-{uuid4()}.mp4",
            filename="jn-test-video.mp4",
            content_type="video/mp4",
            size_bytes=10,
        )
        session.add_all([image, video])
        await session.flush()
        image_id, video_id = image.id, video.id
    async with db.session_scope(staff=True) as session:
        with pytest.raises(ApiError) as caught:
            await admin.create_type(
                admin.TypeCreate(
                    code=code,
                    title_fa="با ویدیو",
                    menu_label_fa="ویدیو",
                    thumbnail_media_id=video_id,
                ),
                REQUEST,
                admin_user,
                session,
            )
        assert caught.value.code == "output_type_invalid"
    async with db.session_scope(staff=True) as session:
        created = await admin.create_type(
            admin.TypeCreate(
                code=code, title_fa="با تصویر", menu_label_fa="تصویر", thumbnail_media_id=image_id
            ),
            REQUEST,
            admin_user,
            session,
        )
    assert created["thumbnail_url"] == f"/v1/help/media/{image_id}"
