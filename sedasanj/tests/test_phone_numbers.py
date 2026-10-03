from app.services.phone_numbers import normalize_call_number


def test_normalizes_persian_and_arabic_digits() -> None:
    assert normalize_call_number("۰۹۱۲۱۲۳۴۵۶۷") == "09121234567"
    assert normalize_call_number("٠٩١٢١٢٣٤٥٦٧") == "09121234567"


def test_normalizes_iranian_country_code_variants() -> None:
    assert normalize_call_number("+98 912 123 4567") == "09121234567"
    assert normalize_call_number("0098-912-123-4567") == "09121234567"
    assert normalize_call_number("98 (0) 912 123 4567") == "09121234567"


def test_normalizes_local_number_without_trunk_prefix() -> None:
    assert normalize_call_number("9121234567") == "09121234567"


def test_preserves_asterisk_extensions_as_ascii_digits() -> None:
    assert normalize_call_number(" داخلی ۱۲۳ ") == "123"
