"""Tenant phonebook: number matching, CSV import parsing and CSV export.

Phone numbers are stored in the same normalised form as `normalize_call_number`, so a call's
caller/dialed number can be matched to a contact regardless of how the PBX wrote it
(`+98912…`, `0098912…`, `0912…`, Persian digits).
"""

from __future__ import annotations

import csv
import io
import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiError
from app.models import Contact
from app.services import extensions, iran_geo
from app.services.phone_numbers import normalize_call_number

ImportMode = Literal["skip", "update"]

MAX_IMPORT_BYTES = 5 * 1024 * 1024
MAX_IMPORT_ROWS = 20_000
MAX_REPORTED_ERRORS = 100
MIN_DIGITS = 3
MAX_DIGITS = 15
LOOKUP_CHUNK = 1000

NAME_MAX = 200
COMPANY_MAX = 200
EMAIL_MAX = 254
NOTES_MAX = 2000

EXPORT_HEADERS = ("نام", "شماره تلفن", "شرکت", "ایمیل", "استان", "شهر", "توضیحات")

# Header aliases, compared after `_header_key` (lower-case, letters and digits only).
_HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "name": (
        "name",
        "fullname",
        "title",
        "contact",
        "contactname",
        "customer",
        "customername",
        "نام",
        "عنوان",
        "مخاطب",
        "مشتری",
        "نامکامل",
        "ناممشتری",
        "نامونامخانوادگی",
    ),
    "phone_number": (
        "phone",
        "phonenumber",
        "number",
        "mobile",
        "mobilenumber",
        "tel",
        "telephone",
        "cell",
        "شماره",
        "شمارهتلفن",
        "شمارهموبایل",
        "شمارهتماس",
        "تلفن",
        "موبایل",
        "همراه",
        "تلفنهمراه",
    ),
    "company": ("company", "organization", "organisation", "org", "شرکت", "سازمان", "نامشرکت"),
    "email": ("email", "mail", "emailaddress", "ایمیل", "پستالکترونیک", "پستالکترونیکی"),
    "province": ("province", "state", "ostan", "استان"),
    "city": ("city", "town", "shahr", "شهر", "شهرستان"),
    "notes": ("notes", "note", "description", "comment", "comments", "توضیحات", "توضیح", "یادداشت"),
}
_ALIAS_TO_FIELD = {
    alias: field_name for field_name, aliases in _HEADER_ALIASES.items() for alias in aliases
}

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_SCIENTIFIC_RE = re.compile(r"^\d(?:[.,]\d+)?[eE][+-]?\d+$")
_TRAILING_ZERO_DECIMAL_RE = re.compile(r"^(\d+)[.,]0+$")
_PHONE_SEPARATORS = frozenset(" -()+./‌‎‏ ‪‬")
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def phone_key(value: str | None) -> str | None:
    """Normalised digits for matching a call number, or None when it is not a usable number."""
    if not value:
        return None
    digits = normalize_call_number(value)
    if MIN_DIGITS <= len(digits) <= MAX_DIGITS:
        return digits
    return None


async def names_for_numbers(
    session: AsyncSession, tenant_id: UUID, numbers: Iterable[str | None]
) -> dict[str, str]:
    """Map normalised phone number -> contact name for the given raw call numbers."""
    raw = list(numbers)
    keys = {key for key in (phone_key(number) for number in raw) if key is not None}
    names: dict[str, str] = {}
    if keys:
        rows = await session.execute(
            select(Contact.phone_number, Contact.name).where(
                Contact.tenant_id == tenant_id, Contact.phone_number.in_(keys)
            )
        )
        names.update(dict(rows.all()))  # type: ignore[arg-type]
    # Internal extensions label themselves (contact, operator or PBX name); a real phonebook
    # number is never overridden.
    for key, label in (await extensions.labels_for(session, tenant_id, raw)).items():
        names.setdefault(key, label)
    return names


def name_for(names: Mapping[str, str], number: str | None) -> str | None:
    key = phone_key(number) or extensions.extension_key(number)
    return names.get(key) if key is not None else None


def _clean(value: str, *, multiline: bool = False) -> str:
    text = unicodedata.normalize("NFC", value).replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("ي", "ی").replace("ك", "ک")  # Arabic forms from Windows-1256 files
    text = _CONTROL_RE.sub("", text)
    if not multiline:
        text = " ".join(text.split())
    text = text.strip()
    # Undo the apostrophe our export puts before a leading = + - @ (spreadsheet formula guard).
    if len(text) > 1 and text[0] == "'" and text[1] in "=+-@":
        text = text[1:]
    return text


def parse_phone(raw: str) -> tuple[str | None, str | None]:
    """Return (normalised digits, None) or (None, Persian reason)."""
    value = raw.strip()
    if not value:
        return None, "شماره تلفن خالی است"
    if _SCIENTIFIC_RE.match(value):
        return None, "شماره به شکل علمی (E+) ذخیره شده؛ در اکسل ستون را به قالب Text تبدیل کنید"
    trailing = _TRAILING_ZERO_DECIMAL_RE.match(value)
    if trailing:
        value = trailing.group(1)
    for character in value:
        if character in _PHONE_SEPARATORS:
            continue
        try:
            unicodedata.decimal(character)
        except (TypeError, ValueError):
            return None, "شماره فقط باید شامل رقم باشد"
    digits = phone_key(value)
    if digits is None:
        return None, f"شماره باید بین {MIN_DIGITS} تا {MAX_DIGITS} رقم باشد"
    return digits, None


@dataclass(frozen=True)
class ContactFields:
    name: str
    phone_number: str
    company: str | None = None
    email: str | None = None
    province: str | None = None
    city: str | None = None
    notes: str | None = None


def resolve_geo(
    province: str | None, city: str | None
) -> tuple[str | None, str | None, str | None]:
    """Canonical (province, city, Persian reason) for free text; only listed names are accepted."""
    raw_province = _clean(province or "")
    raw_city = _clean(city or "")
    if not raw_province:
        if raw_city:
            return None, None, "برای ثبت شهر، استان را هم انتخاب کنید"
        return None, None, None
    matched = iran_geo.match_province(raw_province)
    if matched is None:
        return None, None, "استان در فهرست استان‌های ایران نیست؛ نام را مطابق فهرست بنویسید"
    if not raw_city:
        return matched.name, None, None
    city_name = iran_geo.match_city(matched, raw_city)
    if city_name is None:
        return (
            None,
            None,
            f"شهر در فهرست شهرهای استان {matched.name} نیست؛ نام را مطابق فهرست بنویسید",
        )
    return matched.name, city_name, None


def validate_fields(
    *,
    name: str,
    phone: str,
    company: str | None,
    email: str | None,
    notes: str | None,
    province: str | None = None,
    city: str | None = None,
) -> tuple[ContactFields | None, str | None]:
    """Shared by the form endpoints and the CSV import; reasons are Persian (shown to users)."""
    cleaned_name = _clean(name)
    if not cleaned_name:
        return None, "نام خالی است"
    if len(cleaned_name) > NAME_MAX:
        return None, f"نام بیش از {NAME_MAX} نویسه است"
    digits, reason = parse_phone(phone)
    if digits is None:
        return None, reason
    cleaned_company = _clean(company or "") or None
    if cleaned_company and len(cleaned_company) > COMPANY_MAX:
        return None, f"نام شرکت بیش از {COMPANY_MAX} نویسه است"
    cleaned_email = _clean(email or "").lower() or None
    if cleaned_email and (len(cleaned_email) > EMAIL_MAX or not _EMAIL_RE.match(cleaned_email)):
        return None, "ایمیل معتبر نیست"
    canonical_province, canonical_city, geo_reason = resolve_geo(province, city)
    if geo_reason:
        return None, geo_reason
    cleaned_notes = _clean(notes or "", multiline=True) or None
    if cleaned_notes and len(cleaned_notes) > NOTES_MAX:
        return None, f"توضیحات بیش از {NOTES_MAX} نویسه است"
    fields = ContactFields(
        cleaned_name,
        digits,
        cleaned_company,
        cleaned_email,
        canonical_province,
        canonical_city,
        cleaned_notes,
    )
    return fields, None


def decode_csv(raw: bytes) -> str:
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return raw.decode("utf-16")
        except UnicodeDecodeError as exc:
            raise ApiError("invalid_request", _ENCODING_HELP) from exc
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    try:  # Excel on Persian Windows saves "CSV" as Windows-1256
        return raw.decode("cp1256")
    except UnicodeDecodeError as exc:
        raise ApiError("invalid_request", _ENCODING_HELP) from exc


_ENCODING_HELP = (
    "رمزگذاری فایل شناسایی نشد؛ در اکسل با «CSV UTF-8» ذخیره کنید و دوباره بارگذاری کنید"
)
_NO_HEADER_HELP = (
    "ردیف اول باید عنوان ستون‌ها باشد و شامل ستون «نام» و «شماره تلفن» باشد؛ "
    "فایل نمونه را دریافت و بر همان اساس اصلاح کنید"
)
_EMPTY_HELP = "فایل خالی است؛ فایل CSV دارای ردیف عنوان و مخاطبان را بارگذاری کنید"


def _header_key(value: str) -> str:
    text = value.replace("ي", "ی").replace("ك", "ک")
    return "".join(ch for ch in text.lower() if ch.isalnum())


def _delimiter(first_line: str) -> str:
    counts = {d: first_line.count(d) for d in (",", ";", "\t")}
    best = max(counts, key=lambda d: counts[d])
    return best if counts[best] else ","


@dataclass(frozen=True)
class ImportRow:
    line: int
    fields: ContactFields


@dataclass
class ParsedImport:
    rows: list[ImportRow] = field(default_factory=list)
    errors: list[tuple[int, str]] = field(default_factory=list)
    total_rows: int = 0
    error_count: int = 0

    def add_error(self, line: int, message: str) -> None:
        self.error_count += 1
        if len(self.errors) < MAX_REPORTED_ERRORS:
            self.errors.append((line, message))


def parse_import(raw: bytes) -> ParsedImport:
    """Parse a contacts CSV; row problems are collected, file-level problems raise ApiError."""
    if not raw.strip():
        raise ApiError("invalid_request", _EMPTY_HELP)
    text = decode_csv(raw)
    first_line = next((line for line in text.splitlines() if line.strip()), "")
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=_delimiter(first_line))
    result = ParsedImport()
    columns: dict[str, int] | None = None
    try:
        for line_number, row in enumerate(reader, start=1):
            if not any(cell.strip() for cell in row):
                continue
            if columns is None:
                columns = {}
                for index, header in enumerate(row):
                    mapped = _ALIAS_TO_FIELD.get(_header_key(header))
                    if mapped and mapped not in columns:
                        columns[mapped] = index
                if "name" not in columns or "phone_number" not in columns:
                    raise ApiError("invalid_request", _NO_HEADER_HELP)
                continue
            result.total_rows += 1
            if result.total_rows > MAX_IMPORT_ROWS:
                raise ApiError(
                    "invalid_request",
                    f"حداکثر {MAX_IMPORT_ROWS} ردیف در هر بار ایمپورت مجاز است؛ فایل را تقسیم کنید",
                )
            values = {
                name: (row[index] if index < len(row) else "") for name, index in columns.items()
            }
            fields, reason = validate_fields(
                name=values.get("name", ""),
                phone=values.get("phone_number", ""),
                company=values.get("company"),
                email=values.get("email"),
                notes=values.get("notes"),
                province=values.get("province"),
                city=values.get("city"),
            )
            if fields is None:
                result.add_error(line_number, reason or "ردیف نامعتبر است")
            else:
                result.rows.append(ImportRow(line_number, fields))
    except csv.Error as exc:
        raise ApiError(
            "invalid_request", "ساختار فایل CSV معتبر نیست؛ فایل را در اکسل دوباره ذخیره کنید"
        ) from exc
    if columns is None or result.total_rows == 0:
        raise ApiError("invalid_request", _EMPTY_HELP)
    return result


@dataclass
class ImportOutcome:
    created: int = 0
    updated: int = 0
    skipped: int = 0


async def apply_import(
    session: AsyncSession,
    tenant_id: UUID,
    parsed: ParsedImport,
    *,
    mode: ImportMode,
    dry_run: bool,
    created_by: UUID | None,
) -> ImportOutcome:
    """Insert/update contacts. Within one file the first row for a number wins."""
    outcome = ImportOutcome()
    unique: dict[str, ImportRow] = {}
    for row in parsed.rows:
        if row.fields.phone_number in unique:
            parsed.add_error(
                row.line, "این شماره در ردیف بالاتر همین فایل هم آمده و نادیده گرفته شد"
            )
            continue
        unique[row.fields.phone_number] = row

    existing: dict[str, Contact] = {}
    numbers = list(unique)
    for start in range(0, len(numbers), LOOKUP_CHUNK):
        chunk = numbers[start : start + LOOKUP_CHUNK]
        found = await session.execute(
            select(Contact).where(Contact.tenant_id == tenant_id, Contact.phone_number.in_(chunk))
        )
        existing.update({contact.phone_number: contact for contact in found.scalars()})

    for number, row in unique.items():
        values = row.fields
        current = existing.get(number)
        if current is None:
            outcome.created += 1
            if not dry_run:
                session.add(
                    Contact(
                        tenant_id=tenant_id,
                        phone_number=number,
                        name=values.name,
                        company=values.company,
                        email=values.email,
                        province=values.province,
                        city=values.city,
                        notes=values.notes,
                        created_by=created_by,
                    )
                )
        elif mode == "skip":
            outcome.skipped += 1
        else:
            outcome.updated += 1
            if not dry_run:
                # Empty cells keep the stored value; only filled cells overwrite.
                current.name = values.name
                if values.company is not None:
                    current.company = values.company
                if values.email is not None:
                    current.email = values.email
                if values.province is not None and values.province != current.province:
                    current.province = values.province
                    current.city = values.city  # a new province invalidates the old city
                elif values.city is not None:
                    current.city = values.city
                if values.notes is not None:
                    current.notes = values.notes
    if not dry_run:
        await session.flush()
    return outcome


def _safe_cell(value: str | None) -> str:
    """Neutralise spreadsheet formula injection (OWASP CSV injection) in exported text."""
    if not value:
        return ""
    return "'" + value if value.startswith(_FORMULA_PREFIXES) else value


def _write_csv(rows: Iterable[Contact]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(EXPORT_HEADERS)
    for contact in rows:
        writer.writerow(
            [
                _safe_cell(contact.name),
                contact.phone_number,
                _safe_cell(contact.company),
                _safe_cell(contact.email),
                contact.province or "",
                contact.city or "",
                _safe_cell(contact.notes),
            ]
        )
    return buffer.getvalue()


def export_csv(rows: Iterable[Contact]) -> bytes:
    """UTF-8 with BOM so Excel shows Persian text correctly."""
    return ("﻿" + _write_csv(rows)).encode("utf-8")


def template_csv() -> bytes:
    sample = Contact(
        phone_number="09121234567",
        name="علی رضایی",
        company="شرکت نمونه",
        email="ali@example.com",
        province="تهران",
        city="تهران",
        notes="مشتری ویژه",
    )
    return ("﻿" + _write_csv([sample])).encode("utf-8")
