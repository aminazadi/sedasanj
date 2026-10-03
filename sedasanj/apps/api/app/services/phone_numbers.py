from __future__ import annotations

import unicodedata


def _ascii_digits(value: str) -> str:
    digits: list[str] = []
    for character in value:
        try:
            digits.append(str(unicodedata.decimal(character)))
        except (TypeError, ValueError):
            continue
    return "".join(digits)


def normalize_call_number(value: str) -> str:
    digits = _ascii_digits(value)
    if digits.startswith("0098"):
        digits = digits[4:]
    elif digits.startswith("98") and len(digits) >= 12:
        digits = digits[2:]

    if len(digits) == 10 and not digits.startswith("0"):
        return f"0{digits}"
    if len(digits) == 11 and digits.startswith("0"):
        return digits
    return digits
