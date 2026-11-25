from __future__ import annotations

from app.services.ingest import call_number_issues


def test_valid_numbers_have_no_issues() -> None:
    assert call_number_issues("09121234567", "02112345678", "09121234567", "02112345678") == []


def test_missing_values_are_named() -> None:
    assert call_number_issues(None, None, None, None) == [
        "caller_number is missing",
        "dialed_number is missing",
    ]


def test_a_dialplan_label_is_reported_as_having_no_digits() -> None:
    issues = call_number_issues("09121234567", "recordcheck", "09121234567", "")
    assert issues == ["dialed_number contains no dialable digits"]


def test_the_raw_value_is_never_echoed() -> None:
    issues = call_number_issues("recordcheck", "ivr2", "", "")
    assert issues == [
        "caller_number contains no dialable digits",
        "dialed_number contains no dialable digits",
    ]
    assert all("recordcheck" not in issue and "ivr2" not in issue for issue in issues)


def test_voicemail_does_not_require_a_caller() -> None:
    assert call_number_issues(None, "1001", None, "1001", require_caller=False) == []
