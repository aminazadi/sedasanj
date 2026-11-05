"""Speaker profiles: voiceprint crypto, transcript hash, error codes, help and migrations."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import struct
from pathlib import Path
from types import ModuleType
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from app.config import get_settings
from app.errors import ERROR_STATUS, RETRYABLE_CODES, ApiError
from app.schemas import (
    MeetingTranscriptIn,
    MeetingTranscriptSegmentIn,
    MeetingTranscriptSpeakerIn,
    SpeakerProfilePut,
)
from app.services import voiceprint_crypto as crypto
from app.services.help_content import sanitize_help_html
from app.services.meeting_ingest import transcript_digest

VERSIONS = Path(__file__).resolve().parents[1] / "apps/api/alembic/versions"

SPEAKER_CODES = {
    "speaker_profile_not_found": 404,
    "speaker_profile_conflict": 409,
    "speaker_profile_limit": 409,
    "speaker_consent_required": 422,
    "speaker_voiceprint_invalid": 422,
    "speaker_storage_unavailable": 503,
}


def _load(name: str, filename: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, VERSIONS / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def key(monkeypatch: pytest.MonkeyPatch) -> str:
    value = Fernet.generate_key().decode()
    monkeypatch.setenv("VOICEPRINT_ENCRYPTION_KEY", value)
    get_settings.cache_clear()
    yield value
    get_settings.cache_clear()


@pytest.fixture
def no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VOICEPRINT_ENCRYPTION_KEY", raising=False)
    monkeypatch.setenv("VOICEPRINT_ENCRYPTION_KEY", "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _embedding(dim: int = 16, value: float = 0.25) -> bytes:
    return struct.pack(f"<{dim}f", *([value] * dim))


# ---- voiceprint crypto ------------------------------------------------------------------------


def test_voiceprint_round_trips_and_is_not_stored_in_clear(key: str) -> None:
    sample = uuid4()
    raw = _embedding()
    token = crypto.encrypt_embedding(sample, raw)
    assert raw not in token
    assert crypto.decrypt_embedding(sample, token) == raw
    assert crypto.storage_error() == ""


def test_ciphertext_moved_to_another_sample_is_rejected(key: str) -> None:
    token = crypto.encrypt_embedding(uuid4(), _embedding())
    with pytest.raises(crypto.VoiceprintStorageError):
        crypto.decrypt_embedding(uuid4(), token)


def test_missing_key_fails_closed_without_leaking_anything(no_key: None) -> None:
    assert "VOICEPRINT_ENCRYPTION_KEY" in crypto.storage_error()
    with pytest.raises(crypto.VoiceprintStorageError):
        crypto.encrypt_embedding(uuid4(), _embedding())


def test_invalid_key_is_reported_not_used(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VOICEPRINT_ENCRYPTION_KEY", "not-a-fernet-key")
    get_settings.cache_clear()
    try:
        message = crypto.storage_error()
        assert "valid Fernet" in message
        assert "not-a-fernet-key" not in message
    finally:
        get_settings.cache_clear()


def test_key_rotation_decrypts_old_data_and_encrypts_with_the_first_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old, new = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    sample = uuid4()
    monkeypatch.setenv("VOICEPRINT_ENCRYPTION_KEY", old)
    get_settings.cache_clear()
    try:
        token_old = crypto.encrypt_embedding(sample, _embedding())
        monkeypatch.setenv("VOICEPRINT_ENCRYPTION_KEY", f"{new},{old}")
        get_settings.cache_clear()
        assert crypto.decrypt_embedding(sample, token_old) == _embedding()
        token_new = crypto.encrypt_embedding(sample, _embedding())
        monkeypatch.setenv("VOICEPRINT_ENCRYPTION_KEY", new)
        get_settings.cache_clear()
        assert crypto.decrypt_embedding(sample, token_new) == _embedding()
        with pytest.raises(crypto.VoiceprintStorageError):
            crypto.decrypt_embedding(sample, token_old)
    finally:
        get_settings.cache_clear()


def test_decode_embedding_accepts_a_well_formed_value() -> None:
    raw = _embedding(32)
    assert crypto.decode_embedding(crypto.encode_embedding(raw), 32) == raw


@pytest.mark.parametrize(
    "bad",
    [
        "***not base64***",
        crypto.encode_embedding(_embedding(8)),  # wrong length for dim 16
        crypto.encode_embedding(_embedding(16, 0.0)),  # all zeros
        crypto.encode_embedding(struct.pack("<16f", *([float("nan")] * 16))),
        crypto.encode_embedding(struct.pack("<16f", *([float("inf")] * 16))),
    ],
)
def test_decode_embedding_rejects_malformed_values(bad: str) -> None:
    with pytest.raises(crypto.VoiceprintInvalid):
        crypto.decode_embedding(bad, 16)


# ---- transcript hash ---------------------------------------------------------------------------


def _segments() -> list[MeetingTranscriptSegmentIn]:
    return [
        MeetingTranscriptSegmentIn(t_start_ms=0, t_end_ms=1500, text="سلام", speaker=0),
        MeetingTranscriptSegmentIn(t_start_ms=1500, t_end_ms=3000, text="خوش آمدید", speaker=None),
    ]


def test_hash_of_a_transcript_without_speaker_details_is_unchanged() -> None:
    """The app re-sends text built before these fields existed; its hash must not move."""
    legacy = [
        {"t_start_ms": 0, "t_end_ms": 1500, "text": "سلام", "speaker": 0},
        {"t_start_ms": 1500, "t_end_ms": 3000, "text": "خوش آمدید", "speaker": None},
    ]
    canonical = json.dumps(legacy, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    assert transcript_digest(MeetingTranscriptIn(segments=_segments())) == expected


def test_hash_changes_when_overlap_confidence_or_speaker_names_change() -> None:
    base = transcript_digest(MeetingTranscriptIn(segments=_segments()))
    overlapped = _segments()
    overlapped[0] = overlapped[0].model_copy(update={"overlap": True})
    scored = _segments()
    scored[0] = scored[0].model_copy(update={"speaker_confidence": 80})
    named = MeetingTranscriptIn(
        segments=_segments(), speakers=[MeetingTranscriptSpeakerIn(idx=0, label="سارا")]
    )
    renamed = MeetingTranscriptIn(
        segments=_segments(), speakers=[MeetingTranscriptSpeakerIn(idx=0, label="علی")]
    )
    hashes = {
        base,
        transcript_digest(MeetingTranscriptIn(segments=overlapped)),
        transcript_digest(MeetingTranscriptIn(segments=scored)),
        transcript_digest(named),
        transcript_digest(renamed),
    }
    assert len(hashes) == 5


def test_hash_ignores_the_order_speakers_are_listed_in() -> None:
    a = MeetingTranscriptSpeakerIn(idx=0, label="سارا")
    b = MeetingTranscriptSpeakerIn(idx=1, label="علی")
    first = transcript_digest(MeetingTranscriptIn(segments=_segments(), speakers=[a, b]))
    second = transcript_digest(MeetingTranscriptIn(segments=_segments(), speakers=[b, a]))
    assert first == second


def test_speaker_indexes_must_be_unique() -> None:
    with pytest.raises(ValidationError):
        MeetingTranscriptIn(
            segments=_segments(),
            speakers=[
                MeetingTranscriptSpeakerIn(idx=0, label="سارا"),
                MeetingTranscriptSpeakerIn(idx=0, label="علی"),
            ],
        )


def test_speaker_confidence_is_a_percentage() -> None:
    with pytest.raises(ValidationError):
        MeetingTranscriptSegmentIn(t_start_ms=0, t_end_ms=1, text="x", speaker_confidence=101)


# ---- request validation ------------------------------------------------------------------------


def test_profile_name_is_trimmed_and_must_be_printable() -> None:
    assert SpeakerProfilePut(display_name="  سارا  ", base_version=0).display_name == "سارا"
    for bad in ("   ", "a\nb", ""):
        with pytest.raises(ValidationError):
            SpeakerProfilePut(display_name=bad, base_version=0)


def test_profile_visibility_is_private_or_org() -> None:
    assert SpeakerProfilePut(display_name="x", base_version=0).visibility == "private"
    with pytest.raises(ValidationError):
        SpeakerProfilePut(display_name="x", base_version=0, visibility="public")  # type: ignore[arg-type]


# ---- error codes and help ----------------------------------------------------------------------


@pytest.mark.parametrize(("code", "http_status"), sorted(SPEAKER_CODES.items()))
def test_each_speaker_code_has_its_http_status(code: str, http_status: int) -> None:
    assert ERROR_STATUS[code] == http_status
    assert ApiError(code, "message").status_code == http_status


def test_only_storage_unavailable_is_retryable() -> None:
    assert {code for code in SPEAKER_CODES if code in RETRYABLE_CODES} == {
        "speaker_storage_unavailable"
    }


def test_every_speaker_code_has_a_help_row_with_an_action() -> None:
    module = _load("m0103", "0103_speaker_help_content.py")
    seeded = {code for code, *_ in module.ERRORS}
    assert seeded == set(SPEAKER_CODES)
    assert module.down_revision == "0102_speaker_profiles"
    slugs = [slug for slug, *_ in module.ARTICLES] + [module._slug(code) for code in seeded]
    assert len(slugs) == len(set(slugs))
    assert all(re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", slug) for slug in slugs)
    for code, _title, severity, cause, steps, quick in module.ERRORS:
        assert severity in ("info", "warning", "error", "critical")
        body_html, body_plain = module._body(module.error_blocks(cause, steps, code))
        assert code in body_plain and steps and quick
        assert re.search(r"[؀-ۿ]", body_plain)
        cleaned, _ = sanitize_help_html(body_html)
        assert "<ol>" in cleaned


def test_help_upgrade_binds_every_value(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load("m0103_up", "0103_speaker_help_content.py")
    statements: list[tuple[str, dict]] = []

    class Bind:
        def execute(self, statement, params=None):
            statements.append((str(statement), params or {}))
            return self

        def scalar_one(self):
            return 1

    monkeypatch.setattr(module.op, "get_bind", lambda: Bind())
    module.upgrade()
    assert len([s for s in statements if "INTO help_error_codes" in s[0]]) == len(module.ERRORS)
    assert all(";" not in sql for sql, _ in statements)
    statements.clear()
    module.downgrade()
    assert len(statements) == 2 and all(";" not in sql for sql, _ in statements)


# ---- migration ---------------------------------------------------------------------------------


def _run(direction: str, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    module = _load("m0102", "0102_speaker_profiles.py")
    statements: list[str] = []
    monkeypatch.setattr(module.op, "execute", statements.append)
    getattr(module, direction)()
    return statements


def test_migration_chain_and_single_head() -> None:
    module = _load("m0102_chain", "0102_speaker_profiles.py")
    assert module.revision == "0102_speaker_profiles"
    assert module.down_revision == "0101_report_documents"
    downs = [
        match.group(1)
        for path in VERSIONS.glob("0*.py")
        if (match := re.search(r'^down_revision = "(.+)"', path.read_text(), re.M))
    ]
    assert downs.count("0102_speaker_profiles") == 1


def test_every_new_table_is_granted_and_row_level_secured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sql = _run("upgrade", monkeypatch)
    created = [m.group(1) for s in sql if (m := re.match(r"CREATE TABLE (\w+)", s))]
    assert created == ["speaker_sync_state", "speaker_profiles", "speaker_voiceprints"]
    for table in created:
        assert f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO cbi_app" in sql
        assert f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY" in sql
        assert f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY" in sql
        assert any(f"CREATE POLICY {table}_tenant_isolation ON {table}" in s for s in sql)


def test_migration_is_single_statements_and_reversible(monkeypatch: pytest.MonkeyPatch) -> None:
    up, down = _run("upgrade", monkeypatch), _run("downgrade", monkeypatch)
    assert all(";" not in s for s in up + down)
    for table in ("speaker_sync_state", "speaker_profiles", "speaker_voiceprints"):
        assert f"DROP TABLE IF EXISTS {table}" in down
    # Children drop before parents.
    drops = [s for s in down if s.startswith("DROP TABLE")]
    assert drops.index("DROP TABLE IF EXISTS speaker_voiceprints") < drops.index(
        "DROP TABLE IF EXISTS speaker_profiles"
    )
    assert any("DROP COLUMN IF EXISTS overlap" in s for s in down)
    assert any("DROP COLUMN IF EXISTS profile_id" in s for s in down)


def test_speaker_tables_are_tenant_tables_not_control_only() -> None:
    from app.services.tenant_provisioning import _CONTROL_ONLY

    assert not {"speaker_sync_state", "speaker_profiles", "speaker_voiceprints"} & set(
        _CONTROL_ONLY
    )


# ---- routes ------------------------------------------------------------------------------------


def test_speaker_routes_are_registered_and_stay_out_of_the_public_schema() -> None:
    from plan_routes import api_routes

    from app.main import _public_paths, create_app

    routes = {
        (method, route.path)
        for route in api_routes()
        if route.path.startswith("/v1/meetings/speaker-profiles")
        for method in route.methods
    }
    assert routes == {
        ("GET", "/v1/meetings/speaker-profiles/changes"),
        ("PUT", "/v1/meetings/speaker-profiles/{client_id}"),
        ("DELETE", "/v1/meetings/speaker-profiles/{client_id}"),
    }
    public = _public_paths(create_app().openapi()["paths"])
    assert not [path for path in public if "speaker-profiles" in path]
