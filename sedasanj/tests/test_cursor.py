from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.errors import ApiError
from app.routers.calls import _decode_cursor, _encode_cursor


def test_cursor_roundtrip_preserves_ordering_key() -> None:
    started_at = datetime(2026, 3, 21, 8, 30, tzinfo=UTC)
    call_id = uuid4()
    decoded_at, decoded_id = _decode_cursor(_encode_cursor(started_at, call_id))
    assert decoded_at == started_at
    assert decoded_id == call_id


@pytest.mark.parametrize("cursor", ["", "!!!", "bm90LWEtY3Vyc29y"])
def test_malformed_cursor_is_a_client_error(cursor: str) -> None:
    with pytest.raises(ApiError) as excinfo:
        _decode_cursor(cursor)
    assert excinfo.value.code == "invalid_request"
