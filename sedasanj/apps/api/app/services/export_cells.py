"""Shared spreadsheet cell protection for CSV and XLSX exports."""


def safe_cell(value: str | None) -> str:
    if not value:
        return ""
    # Whitespace and invisible format characters must not hide a formula prefix.
    import unicodedata

    probe = value.lstrip()
    while probe and unicodedata.category(probe[0]) == "Cf":
        probe = probe[1:].lstrip()
    if value.startswith(("\t", "\r", "\n")) or probe.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value
