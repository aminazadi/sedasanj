from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from app.errors import ApiError
from app.services import contacts, extensions


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("101", "101"),
        ("۱۰۱", "101"),
        (" 7001 ", "7001"),
        ("*97", None),
        ("09121234567", None),
        ("", None),
        ("abc", None),
    ],
)
def test_extension_key(raw: str, expected: str | None) -> None:
    assert extensions.extension_key(raw) == expected


def test_short_extension_gets_a_label_but_phone_lookup_still_rejects_it() -> None:
    names = {"101": "علی", "09121234567": "سارا"}
    assert contacts.name_for(names, "101") == "علی"
    assert contacts.name_for(names, "+989121234567") == "سارا"
    assert contacts.name_for(names, "12") is None


def test_label_for() -> None:
    assert extensions.label_for({"101": "علی"}, "101") == "علی"
    assert extensions.label_for({"101": "علی"}, "102") is None
    assert extensions.label_for({}, None) is None


async def test_internal_only_when_both_sides_are_known_extensions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def known(*_: Any) -> set[str]:
        return {"101", "102"}

    monkeypatch.setattr(extensions, "known_extensions", known)
    tenant = uuid4()
    fix = extensions.internal_direction_fixup
    assert await fix(None, tenant, "101", "102", "inbound", None) == ("internal", "102")  # type: ignore[arg-type]
    assert await fix(None, tenant, "101", "102", None, "101") == ("internal", "101")  # type: ignore[arg-type]
    assert await fix(None, tenant, "09121234567", "102", "inbound", None) == ("inbound", None)  # type: ignore[arg-type]
    assert await fix(None, tenant, "101", "103", None, None) == (None, None)  # type: ignore[arg-type]


async def test_sync_rejects_bad_extension_before_touching_the_database() -> None:
    with pytest.raises(ApiError) as exc:
        await extensions.sync(None, uuid4(), [("12ab", "x")])  # type: ignore[arg-type]
    assert exc.value.code == "invalid_request"


def test_clean_name_collapses_whitespace_and_empty() -> None:
    assert extensions.clean_name("  علی   رضایی ") == "علی رضایی"
    assert extensions.clean_name("   ") is None
    assert extensions.clean_name(None) is None
