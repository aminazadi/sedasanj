from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.errors import ApiError
from app.schemas import CallSummary
from app.services import call_export


def _call(**overrides: object) -> CallSummary:
    base: dict[str, object] = {
        "id": uuid4(),
        "asterisk_uniqueid": "1.1",
        "caller_number": "09121234567",
        "dialed_number": "201",
        "direction": "inbound",
        "agent_extension": "201",
        "started_at": datetime(2026, 10, 31, 8, 0, 0, tzinfo=UTC),
        "ended_at": datetime(2026, 10, 31, 8, 1, 5, tzinfo=UTC),
        "updated_at": datetime(2026, 10, 31, 8, 1, 5, tzinfo=UTC),
        "duration_ms": 65000,
        "billed_seconds": 65,
        "status": "complete",
        "error_code": None,
        "summary": "=cmd()",
        "intent": "complaint",
        "caller_name": "علی رضایی",
    }
    base.update(overrides)
    return CallSummary(**base)  # type: ignore[arg-type]


def test_jalali_conversion_uses_tehran_time() -> None:
    assert call_export.to_jalali(datetime(2026, 3, 21, 0, 0, tzinfo=UTC)) == "1405/01/01 03:30:00"
    assert call_export.to_jalali(datetime(2026, 10, 31, 8, 0, tzinfo=UTC)) == "1405/08/09 11:30:00"


def test_columns_follow_catalogue_order_and_reject_unknown_keys() -> None:
    assert call_export.parse_columns("summary,started_at", include_billing=True) == [
        "started_at",
        "summary",
    ]
    with pytest.raises(ApiError):
        call_export.parse_columns("started_at,password", include_billing=True)
    with pytest.raises(ApiError):
        call_export.parse_columns("", include_billing=True)


def test_billing_column_is_hidden_from_operators() -> None:
    with pytest.raises(ApiError):
        call_export.parse_columns("billed_seconds", include_billing=False)


def test_csv_export_labels_values_and_neutralises_formulas() -> None:
    body = call_export.render("csv", ["caller_name", "duration", "intent", "summary"], [_call()])
    lines = body.decode("utf-8-sig").splitlines()
    assert lines[0] == "نام تماس‌گیرنده,مدت (ساعت:دقیقه:ثانیه),قصد,خلاصه"
    assert lines[1] == "علی رضایی,00:01:05,شکایت,'=cmd()"


def test_xlsx_export_is_a_workbook() -> None:
    body = call_export.render("xlsx", ["started_at"], [_call()])
    assert body[:2] == b"PK"
