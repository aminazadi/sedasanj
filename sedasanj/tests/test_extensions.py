from __future__ import annotations

from uuid import uuid4

import pytest

from app.errors import ApiError
from app.services import call_parties, contacts, extensions


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


@pytest.mark.parametrize(
    ("direction", "call_type", "evidence", "origin", "destination", "agent", "expected"),
    [
        ("internal", "answered", "cdr", "۰۱۰۱", "102", None, {"0101": "caller", "102": "callee"}),
        ("internal", "answered", None, None, None, None, {"0101": "caller", "102": "callee"}),
        ("inbound", "answered", "cdr", None, "102", "102", {"102": "agent"}),
        ("inbound", "answered", "ambiguous", None, None, "102", {}),
        ("inbound", "answered", "cdr", None, None, "999", {}),
        ("inbound", "no_answer", "direct", None, None, "102", {}),
        ("inbound", "no_answer", "direct", None, "102", None, {"102": "unanswered_destination"}),
        ("outbound", "answered", "cdr", "0101", None, None, {"0101": "caller"}),
        ("inbound", "voicemail", None, None, None, None, {"102": "mailbox"}),
    ],
)
def test_call_parties(
    direction: str,
    call_type: str,
    evidence: str | None,
    origin: str | None,
    destination: str | None,
    agent: str | None,
    expected: dict[str, str],
) -> None:
    parties = call_parties.classify(
        known={"0101", "102"},
        caller="0101" if direction != "outbound" else "02100000000",
        dialed="102",
        direction=direction,
        agent=agent,
        caller_extension=origin,
        dialed_extension=destination,
        evidence=evidence,
        call_type=call_type,
    )
    assert parties.operator_candidates(call_type) == expected
    if direction == "inbound":
        assert parties.direction == "inbound"


async def test_sync_rejects_bad_extension_before_touching_the_database() -> None:
    with pytest.raises(ApiError) as exc:
        await extensions.sync(None, uuid4(), [("12ab", "x")])  # type: ignore[arg-type]
    assert exc.value.code == "invalid_request"


def test_clean_name_collapses_whitespace_and_empty() -> None:
    assert extensions.clean_name("  علی   رضایی ") == "علی رضایی"
    assert extensions.clean_name("   ") is None
    assert extensions.clean_name(None) is None
