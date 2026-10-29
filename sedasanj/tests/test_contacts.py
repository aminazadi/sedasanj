from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from app.errors import ApiError
from app.models import Contact
from app.services import contacts, iran_geo

HEADER = "نام,شماره تلفن,شرکت,ایمیل,توضیحات\n"


def _csv(body: str, header: str = HEADER) -> bytes:
    return (header + body).encode("utf-8")


def test_call_numbers_match_regardless_of_pbx_format() -> None:
    names = {"09121234567": "علی رضایی", "02112345678": "دفتر مرکزی"}
    for raw in ("09121234567", "+989121234567", "00989121234567", "۰۹۱۲۱۲۳۴۵۶۷", "9121234567"):
        assert contacts.name_for(names, raw) == "علی رضایی"
    assert contacts.name_for(names, "+982112345678") == "دفتر مرکزی"
    assert contacts.name_for(names, "09120000000") is None
    assert contacts.name_for(names, None) is None
    assert contacts.name_for(names, "") is None
    assert contacts.name_for(names, "12") is None  # too short to be a number


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0912 123 4567", "09121234567"),
        ("+98 (912) 123-4567", "09121234567"),
        ("۰۹۱۲۱۲۳۴۵۶۷", "09121234567"),
        ("9121234567", "09121234567"),
        ("9121234567.0", "09121234567"),
        ("1001", "1001"),
    ],
)
def test_parse_phone_accepts_common_spellings(raw: str, expected: str) -> None:
    assert contacts.parse_phone(raw) == (expected, None)


@pytest.mark.parametrize(
    "raw", ["", "abc", "09121234567x", "12", "1234567890123456", "9.12E+09", "0912-ABC"]
)
def test_parse_phone_rejects_bad_values_with_a_reason(raw: str) -> None:
    digits, reason = contacts.parse_phone(raw)
    assert digits is None and reason


def test_import_parses_rows_and_reports_row_errors_with_line_numbers() -> None:
    parsed = contacts.parse_import(
        _csv(
            "علی رضایی,09121234567,شرکت الف,ALI@Example.com,مشتری ویژه\n"
            "\n"
            ",09123334444,,,\n"
            "سارا,abc,,,\n"
            "رضا,09125556666,,bad-email,\n"
            "مریم,+98 912 777 8888,,,\n"
        )
    )
    assert parsed.total_rows == 4 + 1
    assert [row.fields.phone_number for row in parsed.rows] == ["09121234567", "09127778888"]
    assert parsed.rows[0].fields.email == "ali@example.com"
    assert [line for line, _ in parsed.errors] == [4, 5, 6]
    assert parsed.error_count == 3


def test_import_accepts_english_headers_semicolons_and_extra_columns() -> None:
    parsed = contacts.parse_import(
        b"Phone;Full Name;Other\r\n09121234567;Ali Rezaei;x\r\n09120000001;Sara;y\r\n"
    )
    assert [(r.fields.name, r.fields.phone_number) for r in parsed.rows] == [
        ("Ali Rezaei", "09121234567"),
        ("Sara", "09120000001"),
    ]


def test_import_decodes_bom_utf8_and_windows_1256() -> None:
    text = "نام,شماره تلفن\nعلي كريمي,09121234567\n"  # Arabic ي/ك: what cp1256 can encode
    for raw in (b"\xef\xbb\xbf" + text.encode("utf-8"), text.encode("cp1256")):
        parsed = contacts.parse_import(raw)
        assert parsed.rows[0].fields.name == "علی کریمی"


def test_import_handles_quoted_multiline_notes() -> None:
    parsed = contacts.parse_import(_csv('علی,09121234567,,,"خط اول\nخط دوم, ویرگول"\n'))
    assert parsed.rows[0].fields.notes == "خط اول\nخط دوم, ویرگول"


def test_import_rejects_files_without_required_columns_or_content() -> None:
    for raw in (b"", b"  \n \n", _csv("a,b\n", header="x,y\n")):
        with pytest.raises(ApiError) as caught:
            contacts.parse_import(raw)
        assert caught.value.code == "invalid_request"
    with pytest.raises(ApiError):
        contacts.parse_import(HEADER.encode())  # header only: nothing to import


def test_import_enforces_row_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(contacts, "MAX_IMPORT_ROWS", 2)
    with pytest.raises(ApiError):
        contacts.parse_import(_csv("a,0912000001,,,\nb,0912000002,,,\nc,0912000003,,,\n"))


def test_import_error_list_is_capped_but_counted() -> None:
    body = "".join(f"x,bad{i},,,\n" for i in range(150))
    parsed = contacts.parse_import(_csv(body))
    assert parsed.error_count == 150
    assert len(parsed.errors) == contacts.MAX_REPORTED_ERRORS


def test_export_neutralises_spreadsheet_formulas_and_roundtrips() -> None:
    rows = [
        Contact(phone_number="09121234567", name='=HYPERLINK("http://x")', notes="+1"),
        Contact(phone_number="09120000001", name="سارا", company="@evil", email="s@e.com"),
    ]
    raw = contacts.export_csv(rows)
    assert raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig")
    assert "\r\n=" not in text and ",=" not in text and ",+" not in text and ",@" not in text
    parsed = contacts.parse_import(raw)
    assert parsed.error_count == 0
    assert parsed.rows[0].fields.name == '=HYPERLINK("http://x")'
    assert parsed.rows[0].fields.notes == "+1"
    assert parsed.rows[1].fields.company == "@evil"


def test_template_is_importable() -> None:
    parsed = contacts.parse_import(contacts.template_csv())
    assert parsed.error_count == 0 and len(parsed.rows) == 1


class _Result:
    def __init__(self, rows: list[Contact]) -> None:
        self._rows = rows

    def scalars(self) -> list[Contact]:
        return self._rows


class _FakeSession:
    def __init__(self, existing: list[Contact]) -> None:
        self.existing = existing
        self.added: list[Contact] = []
        self.flushed = False

    async def execute(self, _statement: Any) -> _Result:
        return _Result(self.existing)

    def add(self, contact: Contact) -> None:
        self.added.append(contact)

    async def flush(self) -> None:
        self.flushed = True


def _existing() -> Contact:
    return Contact(
        phone_number="09121234567", name="قدیمی", company="شرکت قدیم", email=None, notes="یادداشت"
    )


BODY = "جدید,09121234567,,new@e.com,\nنفر دوم,09120000001,,,\nتکراری,9120000001,,,\n"


async def test_apply_import_skip_mode_only_creates_new_numbers() -> None:
    session = _FakeSession([_existing()])
    parsed = contacts.parse_import(_csv(BODY))
    outcome = await contacts.apply_import(
        session,  # type: ignore[arg-type]
        uuid4(),
        parsed,
        mode="skip",
        dry_run=False,
        created_by=None,
    )
    assert (outcome.created, outcome.updated, outcome.skipped) == (1, 0, 1)
    assert [c.phone_number for c in session.added] == ["09120000001"]
    assert session.existing[0].name == "قدیمی"
    assert parsed.error_count == 1  # duplicate number inside the file
    assert session.flushed


async def test_apply_import_update_mode_keeps_values_for_empty_cells() -> None:
    existing = _existing()
    session = _FakeSession([existing])
    outcome = await contacts.apply_import(
        session,  # type: ignore[arg-type]
        uuid4(),
        contacts.parse_import(_csv(BODY)),
        mode="update",
        dry_run=False,
        created_by=None,
    )
    assert (outcome.created, outcome.updated, outcome.skipped) == (1, 1, 0)
    assert existing.name == "جدید" and existing.email == "new@e.com"
    assert existing.company == "شرکت قدیم" and existing.notes == "یادداشت"


async def test_apply_import_dry_run_changes_nothing() -> None:
    existing = _existing()
    session = _FakeSession([existing])
    outcome = await contacts.apply_import(
        session,  # type: ignore[arg-type]
        uuid4(),
        contacts.parse_import(_csv(BODY)),
        mode="update",
        dry_run=True,
        created_by=None,
    )
    assert (outcome.created, outcome.updated) == (1, 1)
    assert not session.added and not session.flushed and existing.name == "قدیمی"


def test_contact_routes_are_registered_and_static_paths_precede_the_id_route() -> None:
    from app.routers.contacts import router

    paths = [(route.path, sorted(route.methods or [])) for route in router.routes]  # type: ignore[attr-defined]
    ordered = [path for path, _ in paths]
    assert ("/v1/contacts/import", ["POST"]) in paths
    assert ("/v1/contacts/export", ["GET"]) in paths
    assert ordered.index("/v1/contacts/export") < ordered.index("/v1/contacts/{contact_id}")
    assert ordered.index("/v1/contacts/template") < ordered.index("/v1/contacts/{contact_id}")


def test_geo_dataset_lists_all_provinces_with_cities() -> None:
    data = iran_geo.dataset()
    names = [province["name"] for province in data["provinces"]]
    assert len(names) == 31 and len(set(names)) == 31
    assert "تهران" in names and "البرز" in names and "چهارمحال و بختیاری" in names
    assert all(province["cities"] for province in data["provinces"])
    assert data["source"].startswith("iran-cities-json")


@pytest.mark.parametrize(
    ("province", "city", "expected"),
    [
        ("تهران", "تهران", ("تهران", "تهران")),
        ("استان كرمان", "كرمان", ("کرمان", "کرمان")),
        ("چهارمحال و بختیاری", "شهرکرد", ("چهارمحال و بختیاری", "شهرکرد")),
        ("چهار محال وبختیاری", None, ("چهارمحال و بختیاری", None)),
        ("", "", (None, None)),
        (None, None, (None, None)),
    ],
)
def test_resolve_geo_accepts_spelling_variants(
    province: str | None, city: str | None, expected: tuple[str | None, str | None]
) -> None:
    resolved_province, resolved_city, reason = contacts.resolve_geo(province, city)
    assert reason is None and (resolved_province, resolved_city) == expected


@pytest.mark.parametrize(
    ("province", "city"),
    [("نامعتبر", None), ("تهران", "شهرکرد"), (None, "تهران"), ("", "تهران")],
)
def test_resolve_geo_rejects_unknown_names_and_city_without_province(
    province: str | None, city: str | None
) -> None:
    assert contacts.resolve_geo(province, city)[2]


def test_import_reads_province_and_city_columns_and_flags_bad_geo() -> None:
    parsed = contacts.parse_import(
        "نام,شماره,استان,شهر\n"
        "الف,09121111111,تهران,ری\n"
        "ب,09122222222,كرمان,\n"
        "ج,09123333333,آتلانتیس,\n"
        "د,09124444444,تهران,شهرکرد\n".encode()
    )
    assert [(r.fields.province, r.fields.city) for r in parsed.rows] == [
        ("تهران", "ری"),
        ("کرمان", None),
    ]
    assert [line for line, _ in parsed.errors] == [4, 5]


def test_export_includes_geo_and_roundtrips() -> None:
    raw = contacts.export_csv(
        [Contact(phone_number="09121234567", name="الف", province="فارس", city="شیراز")]
    )
    assert "استان" in raw.decode("utf-8-sig").splitlines()[0]
    parsed = contacts.parse_import(raw)
    assert (parsed.rows[0].fields.province, parsed.rows[0].fields.city) == ("فارس", "شیراز")


async def test_update_import_resets_city_when_the_province_changes() -> None:
    existing = Contact(phone_number="09121234567", name="الف", province="فارس", city="شیراز")
    session = _FakeSession([existing])
    await contacts.apply_import(
        session,  # type: ignore[arg-type]
        uuid4(),
        contacts.parse_import("نام,شماره,استان\nالف,09121234567,تهران\n".encode()),
        mode="update",
        dry_run=False,
        created_by=None,
    )
    assert (existing.province, existing.city) == ("تهران", None)
