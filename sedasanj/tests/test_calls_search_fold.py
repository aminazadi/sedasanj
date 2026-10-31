from app.routers.calls import _fold_search_text, _like_pattern


def test_fold_unifies_arabic_letters_and_digits() -> None:
    assert _fold_search_text("  علي   كريم ٠٩١٢۳۴۵  ") == "علی کریم 0912345"


def test_like_pattern_escapes_wildcards() -> None:
    assert _like_pattern("50%_a\\b") == "%50\\%\\_a\\\\b%"
